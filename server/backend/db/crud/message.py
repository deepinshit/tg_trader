# /backend/db/crud/message.py
"""
CRUD helpers for Message entities.

Provides a single function to fetch a Message by its
(telegram chat id, telegram message id) pair with optional eager-loading
of related entities.

Production-ready notes:
- Uses SQLAlchemy 2.0 style (async ORM).
- Explicit eager-loading strategy (joinedload/selectinload).
- Structured logging: includes tg_chat_id, tg_msg_id, and message_id when available.
- Safe error handling with logging context.
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import MultipleResultsFound, SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from models import Message

logger = logging.getLogger(__name__)

__all__ = ["get_message_on_tg_chat_and_msg_id"]


async def get_message_on_tg_chat_and_msg_id(
    session: AsyncSession,
    tg_chat_id: int,
    tg_msg_id: int,
    include_logs: bool = False,
    include_signal: bool = True,
    include_signal_reply: bool = True,
    include_tg_chat: bool = True,
) -> Optional[Message]:
    """
    Fetch a single Message by (tg_chat_id, tg_msg_id).

    Optionally eager-load related entities. Returns None if not found.
    Raises `MultipleResultsFound` if more than one result is found.

    Args:
        session: Active async SQLAlchemy session.
        tg_chat_id: Telegram chat identifier.
        tg_msg_id: Telegram message identifier.
        include_logs: Eager-load `Message.logs` via `selectinload`.
        include_signal: Eager-load `Message.signal` via `joinedload`.
        include_signal_reply: Eager-load `Message.signal_reply` via `joinedload`.
        include_tg_chat: Eager-load `Message.tg_chat` via `joinedload`.

    Returns:
        The matching Message instance or None.
    """
    query = select(Message).where(
        Message.tg_msg_id == tg_msg_id,
        Message.tg_chat_id == tg_chat_id,
    )

    # Dynamically add eager loading
    if include_logs:
        query = query.options(selectinload(Message.logs))
    if include_signal:
        query = query.options(joinedload(Message.signal))
    if include_signal_reply:
        query = query.options(joinedload(Message.signal_reply))
    if include_tg_chat:
        query = query.options(joinedload(Message.tg_chat))

    try:
        result = await session.execute(query)
        message: Optional[Message] = result.scalar_one_or_none()

        extra = {
            "message_id": getattr(message, "id", None),
            "tg_chat_id": tg_chat_id,
            "tg_msg_id": tg_msg_id,
        }

        if message is None:
            logger.debug(
                "No Message found for tg_chat_id=%s, tg_msg_id=%s",
                tg_chat_id,
                tg_msg_id,
                extra=extra,
            )
        else:
            logger.debug(
                "Message fetched for tg_chat_id=%s, tg_msg_id=%s",
                tg_chat_id,
                tg_msg_id,
                extra=extra,
            )

        return message

    except MultipleResultsFound:
        logger.exception(
            "Multiple Message rows found for tg_chat_id=%s, tg_msg_id=%s",
            tg_chat_id,
            tg_msg_id,
            extra={"message_id": None, "tg_chat_id": tg_chat_id, "tg_msg_id": tg_msg_id},
        )
        raise
    except SQLAlchemyError:
        logger.exception(
            "Database error while fetching Message for tg_chat_id=%s, tg_msg_id=%s",
            tg_chat_id,
            tg_msg_id,
            extra={"message_id": None, "tg_chat_id": tg_chat_id, "tg_msg_id": tg_msg_id},
        )
        raise
