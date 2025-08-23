# /backend/distribution/signal_reply.py
"""
SignalReply distribution

This module provides a single entry point, `distribute_signal_reply`, which takes a
`SignalReply` model instance and a `copy_setup_id`, and enqueues a serialized
signal reply into the Redis "pending" queues for all sessions belonging to the
specified copy setup.

Design goals:
- Production-ready and robust: clear validation, defensive logging, graceful
  degradation (one failed session doesn't block others), and proper async
  cancellation handling.
- Clean and not overcomplicated: minimal changes to logic/architecture while
  strengthening reliability.
- Documented and professional: docstrings and type hints.
- Scalable/flexible yet stable: per-session failure isolation and structured logs.

Logging:
- All logs include `extra` with the related DB model id under the key
  `signal_reply_id` (model_name_id requirement) and the `copy_setup_id`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List

from models import SignalReply
from backend.redis.store import RedisStore
from api.schemes import Session, SignalReply as SignalReplyScheme
from backend.distribution.helpers import create_signal_reply_scheme

__all__ = ["distribute_signal_reply"]

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# SignalReply distribution
# ----------------------------------------------------------------------
async def distribute_signal_reply(reply: SignalReply, copy_setup_id: int) -> None:
    """
    Distribute a `SignalReply` into Redis pending queues for all sessions
    of a given copy setup.

    The function is intentionally defensive: it validates inputs, handles
    per-session enqueue errors without stopping the whole distribution, and
    preserves async cancellation semantics.

    Parameters
    ----------
    reply : SignalReply
        The SignalReply ORM/model instance to distribute.
    copy_setup_id : int
        The ID of the copy setup whose sessions should receive the reply.

    Returns
    -------
    None

    Notes
    -----
    - Logging `extra` includes:
        * "signal_reply_id": reply.id         (model_name_id requirement)
        * "copy_setup_id": copy_setup_id
        * (per-session failure only) "client_instance_id"
    """
    # Build common logging context early; be careful if reply.id is missing
    reply_id = getattr(reply, "id", None)
    base_extra = {"signal_reply_id": reply_id, "copy_setup_id": copy_setup_id}

    # Basic input validation (fail fast with clear logs, no exceptions raised here)
    if reply is None or reply_id is None:
        logger.error(
            "distribute_signal_reply called with invalid reply or missing id.",
            extra=base_extra,
        )
        return
    if not isinstance(copy_setup_id, int):
        logger.error(
            "distribute_signal_reply called with non-integer copy_setup_id=%r.",
            copy_setup_id,
            extra=base_extra,
        )
        return

    try:
        async with RedisStore() as redis:
            sessions: List[Session] = await redis.get_sessions_for_copysetup(copy_setup_id)

            if not sessions:
                logger.info(
                    "No sessions found for copy_setup_id=%s; nothing to distribute.",
                    copy_setup_id,
                    extra=base_extra,
                )
                return

            # Serialize the reply once; reuse for all sessions.
            signal_reply_scheme: SignalReplyScheme = create_signal_reply_scheme(reply)

            distributed_count = 0
            total_sessions = len(sessions)

            # Enqueue for each session; isolate per-session failures.
            for sess in sessions:
                try:
                    await redis.add_pending_signal_replies(
                        sess.client_instance_id, [signal_reply_scheme]
                    )
                    distributed_count += 1
                except Exception:
                    # Do not stop on a single failure; log with session context and continue.
                    logger.exception(
                        "Failed to enqueue SignalReply to session client_instance_id=%r.",
                        getattr(sess, "client_instance_id", None),
                        extra={
                            **base_extra,
                            "client_instance_id": getattr(sess, "client_instance_id", None),
                        },
                    )

            if distributed_count:
                logger.info(
                    "Distributed signal_reply_id=%s for copy_setup_id=%s to %s/%s sessions.",
                    reply_id,
                    copy_setup_id,
                    distributed_count,
                    total_sessions,
                    extra=base_extra,
                )
            else:
                logger.warning(
                    "signal_reply_id=%s for copy_setup_id=%s was not distributed to any session.",
                    reply_id,
                    copy_setup_id,
                    extra=base_extra,
                )

    except asyncio.CancelledError:
        # Preserve cooperative cancellation.
        logger.warning(
            "Signal reply distribution cancelled.",
            extra=base_extra,
        )
        raise
    except Exception:
        # Log unexpected failures with full traceback.
        logger.exception(
            "Failed to distribute signal reply.",
            extra=base_extra,
        )
