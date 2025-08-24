# /backend/distribution/signal_reply.py
"""
SignalReply distribution

This module provides a single entry point, `distribute_signal_reply`, which
takes a `SignalReply` model instance and enqueues it into the Redis "pending"
queues for all sessions of all copy setups in the reply's chat.

Design goals:
- Production-ready and robust: clear validation, defensive logging, graceful
  degradation (one failed session doesn't block others), and proper async
  cancellation handling.
- Clean and consistent with `distribute_signal`: preloads relationships,
  structured logging, per-session failure isolation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from models import SignalReply, Message, CopySetup, TgChat
from backend.redis.store import RedisStore
from api.schemes import Session, SignalReply as SignalReplyScheme
from backend.distribution.helpers import create_signal_reply_scheme
from backend.db.functions import get_session_context

__all__ = ["distribute_signal_reply"]

logger = logging.getLogger(__name__)


async def distribute_signal_reply(reply: SignalReply) -> None:
    """
    Distribute a SignalReply to all sessions of all copy setups in its chat.

    Parameters
    ----------
    reply : SignalReply
        The SignalReply ORM/model instance to distribute.

    Returns
    -------
    None
    """
    reply_id = getattr(reply, "id", None)
    base_extra = {"signal_reply_id": reply_id}

    if reply is None or reply_id is None:
        logger.error(
            "distribute_signal_reply called with invalid reply or missing id.",
            extra=base_extra,
        )
        return

    # Preload relationships
    try:
        async with get_session_context() as session:
            async with session.begin():
                stmt = (
                    select(SignalReply)
                    .options(
                        selectinload(SignalReply.message)
                        .selectinload(Message.tg_chat)
                        .selectinload(TgChat.copy_setups)
                        .selectinload(CopySetup.config)
                    )
                    .where(SignalReply.id == reply_id)
                )
                result = await session.execute(stmt)
                reply: Optional[SignalReply] = result.scalars().first()

        if not reply:
            logger.warning(
                "SignalReply not found in DB.",
                extra=base_extra,
            )
            return

        message: Optional[Message] = getattr(reply, "message", None)
        tg_chat: Optional[TgChat] = getattr(message, "tg_chat", None)
        copy_setups: Sequence[CopySetup] = getattr(tg_chat, "copy_setups", [])

        if not copy_setups:
            logger.info(
                "No copy setups associated with SignalReply; nothing to distribute.",
                extra=base_extra,
            )
            return

    except Exception:
        logger.exception(
            "Failed to preload SignalReply relationships.",
            extra=base_extra,
        )
        return

    # Distribute to Redis
    try:
        async with RedisStore() as redis:
            for cs in copy_setups:
                cs_id = getattr(cs, "id", None)
                cs_extra = {**base_extra, "copy_setup_id": cs_id}

                if cs_id is None:
                    logger.warning(
                        "CopySetup missing id; skipping.",
                        extra=cs_extra,
                    )
                    continue

                try:
                    sessions: List[Session] = await redis.get_sessions_by_copysetup(cs_id)
                    if not sessions:
                        logger.debug(
                            "No active sessions for copy setup; skipping.",
                            extra=cs_extra,
                        )
                        continue

                    scheme: SignalReplyScheme = create_signal_reply_scheme(reply)

                    distributed_count = 0
                    total_sessions = len(sessions)

                    for sess in sessions:
                        client_id = getattr(sess, "client_instance_id", None)
                        try:
                            await redis.add_pending_signal_replies(client_id, [scheme])
                            distributed_count += 1
                        except Exception:
                            logger.exception(
                                "Failed to enqueue SignalReply to session.",
                                extra={**cs_extra, "client_instance_id": client_id},
                            )

                    if distributed_count:
                        logger.info(
                            "Distributed SignalReply to %d/%d sessions.",
                            distributed_count,
                            total_sessions,
                            extra=cs_extra,
                        )
                    else:
                        logger.warning(
                            "SignalReply generated but not distributed to any session.",
                            extra=cs_extra,
                        )

                except Exception:
                    logger.exception(
                        "Failed to distribute SignalReply for copy setup.",
                        extra=cs_extra,
                    )

    except asyncio.CancelledError:
        logger.warning(
            "SignalReply distribution cancelled.",
            extra=base_extra,
        )
        raise
    except Exception:
        logger.exception(
            "Failed to distribute SignalReply.",
            extra=base_extra,
        )
