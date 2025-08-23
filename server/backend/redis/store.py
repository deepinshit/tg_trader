# backend/redis/store.py
"""
High-quality async Redis store for sessions, pending trades, and pending signal replies.

Design goals:
  - Robust: retry with exponential backoff + jitter on transient Redis errors.
  - Efficient: SCAN + batched MGET for reads, pipelining for throughput.
  - Simple: small clear API; per-item TTL via atomic SET EX.
  - Safe: explicit IDs; no hidden server-side mutations.
  - Typed: integrates with Pydantic models from api.schemes.

Key patterns (namespace is prepended if provided):
  session:{refresh_token}
  pending:{client_instance_id}:trades:{trade_id}
  pending:{client_instance_id}:signal_replies:{reply_id}
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional, Sequence, Type, TypeVar, Union

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError, TimeoutError
from pydantic import BaseModel

# Import your API schemas (adjust the import path if your project layout differs)
from api.schemes import Session as SessionSchema
from api.schemes import Trade as TradeSchema
from api.schemes import SignalReply as SignalReplySchema

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

class RedisStore:
    """
    Async Redis access layer.

    Typical usage (as dependency):
        store = RedisStore(url=settings.REDIS_URL, namespace="myapp")
        await store.connect()
        ...
        await store.close()

    Or with async context manager:
        async with RedisStore(...) as store:
            await store.add_session(...)
    """

    # ---- Tuning knobs ----
    SCAN_COUNT = 512         # how many keys per SCAN round
    MGET_BATCH = 512         # how many keys per MGET batch
    RETRIES = 3              # retry attempts on transient errors
    BACKOFF_BASE = 0.12      # seconds; exponential backoff base (with jitter)

    def __init__(self, url: str = "redis://localhost:6379/0", namespace: str = "") -> None:
        self._url = url
        # Prefix all keys if namespace provided (e.g., "prod", "staging")
        self._ns = f"{namespace}:" if namespace else ""
        self._r: Optional[aioredis.Redis] = None

    # ---------------------------
    # Lifecycle
    # ---------------------------
    async def connect(self) -> None:
        if self._r is None:
            self._r = aioredis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
                health_check_interval=30,
                socket_keepalive=True,
            )
            # Touch Redis once to fail fast if misconfigured
            await self._with_retry(self._r.ping)
            logger.info("RedisStore connected")

    async def close(self) -> None:
        if self._r is not None:
            await self._r.close()
            self._r = None
            logger.info("RedisStore closed")

    async def __aenter__(self) -> "RedisStore":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ---------------------------
    # Retry wrapper (exponential backoff + jitter)
    # ---------------------------
    async def _with_retry(self, func, *args, **kwargs):
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.RETRIES + 1):
            try:
                return await func(*args, **kwargs)
            except (ConnectionError, TimeoutError) as e:
                last_exc = e
                # Exponential backoff with jitter
                sleep_s = (self.BACKOFF_BASE * (2 ** (attempt - 1))) + random.uniform(0, 0.05)
                if attempt < self.RETRIES:
                    await asyncio.sleep(sleep_s)
                else:
                    logger.error("Redis operation failed after retries", exc_info=True)
        if last_exc:
            raise last_exc

    # ---------------------------
    # Key helpers
    # ---------------------------
    def _session_key(self, refresh_token: str) -> str:
        return f"{self._ns}session:{refresh_token}"

    def _trade_key(self, client_instance_id: str, trade_id: Union[int, str]) -> str:
        return f"{self._ns}pending:{client_instance_id}:trades:{trade_id}"

    def _reply_key(self, client_instance_id: str, reply_id: Union[int, str]) -> str:
        return f"{self._ns}pending:{client_instance_id}:signal_replies:{reply_id}"

    # ---------------------------
    # Serialization helpers
    # ---------------------------
    @staticmethod
    def _to_json(payload: Union[BaseModel, Dict[str, Any]]) -> str:
        if isinstance(payload, BaseModel):
            # Pydantic handles datetime serialization cleanly (ISO 8601)
            return payload.model_dump_json() if hasattr(payload, "model_dump_json") else payload.json()
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _parse_json(model: Type[T], raw: Optional[str]) -> Optional[T]:
        if not raw:
            return None
        # Support Pydantic v1/v2
        try:
            if hasattr(model, "model_validate_json"):
                return model.model_validate_json(raw)  # Pydantic v2
            return model.parse_raw(raw)  # Pydantic v1
        except Exception:
            logger.exception("Failed to parse JSON into %s", model.__name__)
            return None

    # ---------------------------
    # Sessions
    # ---------------------------
    async def add_session(self, session: Union[SessionSchema, Dict[str, Any]], ttl: Optional[int] = None) -> bool:
        """
        Create or overwrite a session (atomic with TTL when provided).

        Args:
            session: SessionSchema or dict with at least 'refresh_token'
            ttl: seconds to live; if None, key lives until deleted

        Returns:
            True on success.

        Raises:
            KeyError if 'refresh_token' missing.
            RedisError on persistent Redis failure.
        """
        if isinstance(session, dict):
            refresh_token = session.get("refresh_token")
            if not refresh_token:
                raise KeyError("session.refresh_token is required")
        else:
            refresh_token = session.refresh_token

        key = self._session_key(refresh_token)
        payload = self._to_json(session)
        if ttl:
            await self._with_retry(self._r.set, key, payload, ex=ttl)  # atomic set+ttl
        else:
            await self._with_retry(self._r.set, key, payload)
        return True

    async def update_session(self, refresh_token: str, updates: Dict[str, Any]) -> bool:
        """
        Merge updates into an existing session. Returns False if it does not exist.
        """
        key = self._session_key(refresh_token)
        raw = await self._with_retry(self._r.get, key)
        if raw is None:
            return False
        data = json.loads(raw)
        data.update(updates or {})
        await self._with_retry(self._r.set, key, json.dumps(data, separators=(",", ":")))
        return True

    async def get_session(self, refresh_token: str) -> Optional[SessionSchema]:
        """
        Fetch a session by refresh_token, or None if missing.
        """
        raw = await self._with_retry(self._r.get, self._session_key(refresh_token))
        return self._parse_json(SessionSchema, raw)

    async def delete_session(self, refresh_token: str) -> bool:
        """
        Delete a session. Returns True if a key was removed.
        """
        removed = await self._with_retry(self._r.delete, self._session_key(refresh_token))
        return bool(removed)

    async def get_sessions_for_copysetup(self, copy_setup_id: int, limit: Optional[int] = None) -> List[SessionSchema]:
        """
        Scan all sessions and return those matching copy_setup_id.
        Uses SCAN to avoid blocking Redis; values are MGET'd in batches.

        NOTE: O(N) over total sessions; if this becomes hot, add a secondary
              index like: set 'copysetup:{id}:sessions' with refresh_tokens.
        """
        pattern = f"{self._ns}session:*"
        out: List[SessionSchema] = []
        cursor = 0

        while True:
            cursor, keys = await self._with_retry(self._r.scan, cursor=cursor, match=pattern, count=self.SCAN_COUNT)
            if keys:
                # batch MGET
                for batch_start in range(0, len(keys), self.MGET_BATCH):
                    batch_keys = keys[batch_start : batch_start + self.MGET_BATCH]
                    values = await self._with_retry(self._r.mget, batch_keys)
                    for raw in values:
                        sess = self._parse_json(SessionSchema, raw)
                        if sess and sess.copy_setup_id == copy_setup_id:
                            out.append(sess)
                            if limit and len(out) >= limit:
                                return out
            if cursor == 0:
                break

        return out

    # ---------------------------
    # Pending Trades
    # ---------------------------
    async def add_pending_trades(
        self,
        client_instance_id: str,
        trades: Sequence[Union[TradeSchema, Dict[str, Any]]],
        ttl: Optional[int] = None,
    ) -> int:
        """
        Add multiple pending trades (each must have unique 'id' per client).
        TTL applies per-trade atomically via SET EX.

        Returns:
            Number of trades added.
        """
        if not trades:
            return 0

        pipe = self._r.pipeline(transaction=False)
        count = 0
        for tr in trades:
            tid = tr["id"] if isinstance(tr, dict) else tr.id
            key = self._trade_key(client_instance_id, tid)
            payload = self._to_json(tr)
            if ttl:
                pipe.set(key, payload, ex=ttl)
            else:
                pipe.set(key, payload)
            count += 1

        await self._with_retry(pipe.execute)
        return count

    async def get_pending_trades(self, client_instance_id: str, limit: Optional[int] = None) -> List[TradeSchema]:
        """
        Get all or the first 'limit' pending trades for a client.
        """
        pattern = f"{self._ns}pending:{client_instance_id}:trades:*"
        out: List[TradeSchema] = []
        cursor = 0

        while True:
            cursor, keys = await self._with_retry(self._r.scan, cursor=cursor, match=pattern, count=self.SCAN_COUNT)
            if keys:
                for batch_start in range(0, len(keys), self.MGET_BATCH):
                    batch_keys = keys[batch_start : batch_start + self.MGET_BATCH]
                    values = await self._with_retry(self._r.mget, batch_keys)
                    for raw in values:
                        trade = self._parse_json(TradeSchema, raw)
                        if trade:
                            out.append(trade)
                            if limit and len(out) >= limit:
                                return out
            if cursor == 0:
                break

        return out

    async def delete_pending_trades(self, client_instance_id: str, trade_ids: Sequence[Union[int, str]]) -> int:
        """
        Delete specific pending trades by ID. Returns number of keys deleted.
        """
        if not trade_ids:
            return 0
        keys = [self._trade_key(client_instance_id, tid) for tid in trade_ids]
        deleted = await self._with_retry(self._r.delete, *keys)
        return int(deleted or 0)

    # ---------------------------
    # Pending Signal Replies
    # ---------------------------
    async def add_pending_signal_replies(
        self,
        client_instance_id: str,
        replies: Sequence[Union[SignalReplySchema, Dict[str, Any]]],
        ttl: Optional[int] = None,
    ) -> int:
        """
        Add multiple pending signal replies (each must have unique 'id' per client).
        TTL applies per-reply atomically via SET EX.

        Returns:
            Number of replies added.
        """
        if not replies:
            return 0

        pipe = self._r.pipeline(transaction=False)
        count = 0
        for rp in replies:
            rid = rp["id"] if isinstance(rp, dict) else rp.id
            key = self._reply_key(client_instance_id, rid)
            payload = self._to_json(rp)
            if ttl:
                pipe.set(key, payload, ex=ttl)
            else:
                pipe.set(key, payload)
            count += 1

        await self._with_retry(pipe.execute)
        return count

    async def get_pending_signal_replies(self, client_instance_id: str, limit: Optional[int] = None) -> List[SignalReplySchema]:
        """
        Get all or the first 'limit' pending signal replies for a client.
        """
        pattern = f"{self._ns}pending:{client_instance_id}:signal_replies:*"
        out: List[SignalReplySchema] = []
        cursor = 0

        while True:
            cursor, keys = await self._with_retry(self._r.scan, cursor=cursor, match=pattern, count=self.SCAN_COUNT)
            if keys:
                for batch_start in range(0, len(keys), self.MGET_BATCH):
                    batch_keys = keys[batch_start : batch_start + self.MGET_BATCH]
                    values = await self._with_retry(self._r.mget, batch_keys)
                    for raw in values:
                        reply = self._parse_json(SignalReplySchema, raw)
                        if reply:
                            out.append(reply)
                            if limit and len(out) >= limit:
                                return out
            if cursor == 0:
                break

        return out

    async def delete_pending_signal_replies(self, client_instance_id: str, reply_ids: Sequence[Union[int, str]]) -> int:
        """
        Delete specific pending signal replies by ID. Returns number of keys deleted.
        """
        if not reply_ids:
            return 0
        keys = [self._reply_key(client_instance_id, rid) for rid in reply_ids]
        deleted = await self._with_retry(self._r.delete, *keys)
        return int(deleted or 0)
