# /backend/db/crud/tg_chat.py
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

# Models should be pure SQLAlchemy 2.0 declarative classes
from models import TgChat, CopySetup
# Use your project's AsyncSession alias; if you use SQLAlchemy directly, it would be:
# from sqlalchemy.ext.asyncio import AsyncSession
from backend.db.functions import AsyncSession

__all__ = ["get_tg_chat_on_id"]

logger = logging.getLogger(__name__)


async def get_tg_chat_on_id(
    session: AsyncSession,
    id: int,
    include_messages: bool = False,
    include_copy_setups: bool = True,
) -> Optional[TgChat]:
    """
    Fetch a TgChat by its primary key.

    Eager-loading is opt-in for related collections to keep the default query lean.
    - Messages can be loaded via `selectinload(TgChat.messages)`.
    - Copy setups can be loaded via `selectinload(TgChat.copy_setups).joinedload(CopySetup.config)`.

    Parameters
    ----------
    session : AsyncSession
        The async SQLAlchemy session.
    id : int
        The TgChat ID to retrieve (can be negative if such IDs are valid in the domain).
    include_messages : bool, optional
        If True, eagerly loads TgChat.messages. Defaults to False.
    include_copy_setups : bool, optional
        If True, eagerly loads TgChat.copy_setups and their .config. Defaults to True.

    Returns
    -------
    Optional[TgChat]
        The TgChat instance if found; otherwise None.

    Notes
    -----
    - Uses `selectinload` for collections to minimize round-trips vs. N+1.
    - Uses `joinedload` for single-valued `CopySetup.config` to fetch in the same round-trip.
    - Raises on DB/driver errors with context logged; returns None only when no row matches.
    """
    model_id = id  # keep local for logging consistency

    try:
        query = select(TgChat).where(TgChat.id == model_id)

        # Compose loader options based on flags
        load_options = []
        if include_messages:
            load_options.append(selectinload(TgChat.messages))
        if include_copy_setups:
            load_options.append(
                selectinload(TgChat.copy_setups).joinedload(CopySetup.config)
            )

        if load_options:
            query = query.options(*load_options)

        logger.debug(
            "Executing TgChat lookup query.",
            extra={"tg_chat_id": model_id},
        )

        result = await session.execute(query)
        chat: Optional[TgChat] = result.scalar_one_or_none()

        logger.debug(
            "TgChat lookup completed.",
            extra={"tg_chat_id": model_id, "found": chat is not None},
        )

        return chat

    except SQLAlchemyError:
        # SQLAlchemy/driver error (connection issues, syntax errors, etc.)
        logger.exception(
            "Database error during TgChat lookup.",
            extra={"model": "TgChat", "model_id": model_id},
        )
        raise
    except Exception:
        # Any unexpected runtime error
        logger.exception(
            "Unexpected error during TgChat lookup.",
            extra={"model": "TgChat", "model_id": model_id},
        )
        raise

