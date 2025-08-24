# /backend/db/crud/copy_setup.py
"""
CRUD helpers for CopySetup entities.

Provides a single function to fetch a CopySetup by its
token, with optional eager-loading of related entities.

Production-ready notes:
- Uses SQLAlchemy 2.0 style async ORM.
- Explicit eager-loading strategy (joinedload/selectinload).
- Structured logging: includes token and model info.
- Safe error handling with proper exception logging.
"""

import logging
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.exc import MultipleResultsFound, SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from models import CopySetup

logger = logging.getLogger(__name__)

__all__ = ["get_copy_setup"]

from sqlalchemy import select
from sqlalchemy.orm import selectinload

async def get_copy_setup_on_token(db: AsyncSession, token: str):
    result = await db.execute(
        select(CopySetup)
        .where(CopySetup.cs_token == token)
        .options(selectinload(CopySetup.config))  # Eager-load the config
    )
    return result.scalars().first()

async def get_copy_setup_on_token1(
    session: AsyncSession,
    cs_token: str,
    include_logs: bool = False,
    include_config: bool = True,
    include_mt5_trades: bool = False,
    include_user: bool = False,
    include_tg_chats: bool = False,
) -> Optional[CopySetup]:
    """
    Fetch a CopySetup by its `cs_token`.

    Args:
        session (AsyncSession): SQLAlchemy async session.
        cs_token (str): Unique token identifying the CopySetup.
        include_logs (bool): Whether to eager-load related logs (selectinload).
        include_config (bool): Whether to eager-load config (joinedload).
        include_mt5_trades (bool): Whether to eager-load MT5 trades (selectinload).
        include_user (bool): Whether to eager-load the user relationship (joinedload).
        include_tg_chats (bool): Whether to eager-load related Telegram chats (selectinload).

    Returns:
        Optional[CopySetup]: The matching CopySetup object, or None if not found.

    Raises:
        MultipleResultsFound: If multiple results are returned (should not happen if token is unique).
        SQLAlchemyError: If a database error occurs.
    """
    query = select(CopySetup).where(CopySetup.cs_token == cs_token)

    # Dynamically add eager loading
    if include_logs:
        query = query.options(selectinload(CopySetup.logs))
    if include_config:
        query = query.options(joinedload(CopySetup.config))
    if include_mt5_trades:
        query = query.options(selectinload(CopySetup.mt5_trades))
    if include_user:
        query = query.options(joinedload(CopySetup.user))
    if include_tg_chats:
        query = query.options(selectinload(CopySetup.tg_chats))

    try:
        result = await session.execute(query)
        copy_setup: Optional[CopySetup] = result.scalar_one_or_none()

        if copy_setup is None:
            logger.debug("No CopySetup found for token=%s", cs_token)

        return copy_setup

    except MultipleResultsFound:
        logger.exception("Multiple CopySetups found for token=%s", cs_token)
        raise
    except SQLAlchemyError:
        logger.exception("Database error while fetching CopySetup for token=%s", cs_token)
        raise


async def get_copy_setups_on_user_id(
    session: AsyncSession,
    user_id: int,
    include_logs: bool = False,
    include_config: bool = True,
    include_mt5_trades: bool = False,
    include_user: bool = False,
    include_tg_chats: bool = False,
) -> List[CopySetup]:
    """
    Fetch a CopySetup by its `cs_token`.

    Args:
        session (AsyncSession): SQLAlchemy async session.
        cs_token (str): Unique token identifying the CopySetup.
        include_logs (bool): Whether to eager-load related logs (selectinload).
        include_config (bool): Whether to eager-load config (joinedload).
        include_mt5_trades (bool): Whether to eager-load MT5 trades (selectinload).
        include_user (bool): Whether to eager-load the user relationship (joinedload).
        include_tg_chats (bool): Whether to eager-load related Telegram chats (selectinload).

    Returns:
        Optional[CopySetup]: The matching CopySetup object, or None if not found.

    Raises:
        MultipleResultsFound: If multiple results are returned (should not happen if token is unique).
        SQLAlchemyError: If a database error occurs.
    """
    query = select(CopySetup).where(CopySetup.user_id == user_id)

    # Dynamically add eager loading
    if include_logs:
        query = query.options(selectinload(CopySetup.logs))
    if include_config:
        query = query.options(joinedload(CopySetup.config))
    if include_mt5_trades:
        query = query.options(selectinload(CopySetup.mt5_trades))
    if include_user:
        query = query.options(joinedload(CopySetup.user))
    if include_tg_chats:
        query = query.options(selectinload(CopySetup.tg_chats))

    try:
        result = await session.execute(query)
        copy_setups: List[CopySetup] = list(result.scalars().all())

        if not copy_setups:
            logger.debug("No CopySetups found", extra={"user_id": user_id})

        return copy_setups
    except SQLAlchemyError:
        logger.exception("Database error while fetching CopySetup's", extra={"user_id": user_id})
        raise

