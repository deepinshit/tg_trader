# backend/redis/store.py
"""
High-quality async Redis store for sessions, pending trades, and pending signal replies.

Features:
- Sessions: indexed by refresh_token, client_instance_id, copy_setup_id
- Pending trades & signal replies: per-client with TTL
- Robust: retries with exponential backoff + jitter
- Efficient: SCAN + batched MGET, pipelining for writes
- Async & user-friendly API
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

from api.schemes import Session as SessionSchema
from api.schemes import Trade as TradeSchema
from api.schemes import SignalReply as SignalReplySchema

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class RedisStore:
    SCAN_COUNT = 512
    MGET_BATCH = 512
    RETRIES = 3
    BACKOFF_BASE = 0.12

    def __init__(self, url: str = "redis://localhost:6379/0", namespace: str = "") -> None:
        self._url = url
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
            await self._with_retry(self._r.ping)
            logger.info("RedisStore connected")

    async def close(self) -> None:
        if self._r:
            await self._r.close()
            self._r = None
            logger.info("RedisStore closed")

    async def __aenter__(self) -> "RedisStore":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ---------------------------
    # Retry wrapper
    # ---------------------------
    async def _with_retry(self, func, *args, **kwargs):
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.RETRIES + 1):
            try:
                return await func(*args, **kwargs)
            except (ConnectionError, TimeoutError) as e:
                last_exc = e
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

    def _client_key(self, client_instance_id: str) -> str:
        return f"{self._ns}client_session:{client_instance_id}"

    def _copysetup_key(self, copy_setup_id: int) -> str:
        return f"{self._ns}copysetup_sessions:{copy_setup_id}"

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
            return payload.model_dump_json() if hasattr(payload, "model_dump_json") else payload.json()
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _parse_json(model: Type[T], raw: Optional[str]) -> Optional[T]:
        if not raw:
            return None
        try:
            if hasattr(model, "model_validate_json"):
                return model.model_validate_json(raw)
            return model.parse_raw(raw)
        except Exception:
            logger.exception("Failed to parse JSON into %s", model.__name__)
            return None

    # ---------------------------
    # Session operations
    # ---------------------------
    async def add_session(self, session: Union[SessionSchema, Dict[str, Any]], ttl: Optional[int] = None) -> bool:
        if isinstance(session, dict):
            refresh_token = session.get("refresh_token")
            client_id = session.get("client_instance_id")
            copy_id = session.get("copy_setup_id")
            if not refresh_token or not client_id or copy_id is None:
                raise KeyError("refresh_token, client_instance_id, copy_setup_id are required")
        else:
            refresh_token = session.refresh_token
            client_id = session.client_instance_id
            copy_id = session.copy_setup_id

        key = self._session_key(refresh_token)
        payload = self._to_json(session)

        pipe = self._r.pipeline(transaction=True)
        if ttl:
            pipe.set(key, payload, ex=ttl)
        else:
            pipe.set(key, payload)
        pipe.set(self._client_key(client_id), refresh_token)
        pipe.sadd(self._copysetup_key(copy_id), refresh_token)
        await self._with_retry(pipe.execute)
        return True

    async def get_session(self, refresh_token: str) -> Optional[SessionSchema]:
        raw = await self._with_retry(self._r.get, self._session_key(refresh_token))
        return self._parse_json(SessionSchema, raw)

    async def get_session_by_client(self, client_instance_id: str) -> Optional[SessionSchema]:
        refresh_token = await self._with_retry(self._r.get, self._client_key(client_instance_id))
        if not refresh_token:
            return None
        return await self.get_session(refresh_token)

    async def get_sessions_by_copysetup(self, copy_setup_id: int, limit: Optional[int] = None) -> List[SessionSchema]:
        refresh_tokens = await self._with_retry(self._r.smembers, self._copysetup_key(copy_setup_id))
        if not refresh_tokens:
            return []

        sessions: List[SessionSchema] = []
        tokens = list(refresh_tokens)
        for i in range(0, len(tokens), self.MGET_BATCH):
            batch = tokens[i:i+self.MGET_BATCH]
            values = await self._with_retry(self._r.mget, [self._session_key(t) for t in batch])
            for raw in values:
                sess = self._parse_json(SessionSchema, raw)
                if sess:
                    sessions.append(sess)
                    if limit and len(sessions) >= limit:
                        return sessions
        return sessions

    async def update_session(self, refresh_token: str, updates: Dict[str, Any]) -> bool:
        key = self._session_key(refresh_token)
        raw = await self._with_retry(self._r.get, key)
        if not raw:
            return False

        session_data = json.loads(raw)
        old_client = session_data.get("client_instance_id")
        old_copy = session_data.get("copy_setup_id")
        session_data.update(updates)
        new_client = session_data.get("client_instance_id")
        new_copy = session_data.get("copy_setup_id")

        pipe = self._r.pipeline(transaction=True)
        pipe.set(key, json.dumps(session_data, separators=(",", ":")))
        if old_client != new_client:
            pipe.set(self._client_key(new_client), refresh_token)
        if old_copy != new_copy:
            pipe.srem(self._copysetup_key(old_copy), refresh_token)
            pipe.sadd(self._copysetup_key(new_copy), refresh_token)
        await self._with_retry(pipe.execute)
        return True

    async def delete_session(self, refresh_token: str) -> bool:
        raw = await self._with_retry(self._r.get, self._session_key(refresh_token))
        if not raw:
            return False
        session = json.loads(raw)
        client_id = session.get("client_instance_id")
        copy_id = session.get("copy_setup_id")

        pipe = self._r.pipeline(transaction=True)
        pipe.delete(self._session_key(refresh_token))
        if client_id:
            pipe.delete(self._client_key(client_id))
        if copy_id is not None:
            pipe.srem(self._copysetup_key(copy_id), refresh_token)
        await self._with_retry(pipe.execute)
        return True

    # ---------------------------
    # Pending trades
    # ---------------------------
    async def add_pending_trades(
        self,
        client_instance_id: str,
        trades: Sequence[Union[TradeSchema, Dict[str, Any]]],
        ttl: Optional[int] = None,
    ) -> int:
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
        pattern = f"{self._ns}pending:{client_instance_id}:trades:*"
        out: List[TradeSchema] = []
        cursor = 0
        while True:
            cursor, keys = await self._with_retry(self._r.scan, cursor=cursor, match=pattern, count=self.SCAN_COUNT)
            if keys:
                for batch_start in range(0, len(keys), self.MGET_BATCH):
                    batch_keys = keys[batch_start: batch_start + self.MGET_BATCH]
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
        if not trade_ids:
            return 0
        keys = [self._trade_key(client_instance_id, tid) for tid in trade_ids]
        deleted = await self._with_retry(self._r.delete, *keys)
        return int(deleted or 0)

    # ---------------------------
    # Pending signal replies
    # ---------------------------
    async def add_pending_signal_replies(
        self,
        client_instance_id: str,
        replies: Sequence[Union[SignalReplySchema, Dict[str, Any]]],
        ttl: Optional[int] = None,
    ) -> int:
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
        pattern = f"{self._ns}pending:{client_instance_id}:signal_replies:*"
        out: List[SignalReplySchema] = []
        cursor = 0
        while True:
            cursor, keys = await self._with_retry(self._r.scan, cursor=cursor, match=pattern, count=self.SCAN_COUNT)
            if keys:
                for batch_start in range(0, len(keys), self.MGET_BATCH):
                    batch_keys = keys[batch_start: batch_start + self.MGET_BATCH]
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
        if not reply_ids:
            return 0
        keys = [self._reply_key(client_instance_id, rid) for rid in reply_ids]
        deleted = await self._with_retry(self._r.delete, *keys)
        return int(deleted or 0)
