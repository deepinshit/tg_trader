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

from models import CopySetupConfig

logger = logging.getLogger(__name__)

__all__ = ["get_copy_setup_configs"]

async def get_copy_setup_configs_on_user_id(
    session: AsyncSession,
    user_id: int,
    include_copy_setups: bool = False,
    include_user: bool = False,
) -> List[CopySetupConfig]:
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
    query = select(CopySetupConfig).where(CopySetupConfig.user_id == user_id)

    # Dynamically add eager loading
    if include_copy_setups:
        query = query.options(selectinload(CopySetupConfig.copy_setups))
    if include_user:
        query = query.options(joinedload(CopySetupConfig.user))

    try:
        result = await session.execute(query)
        copy_setup_configs: List[CopySetupConfig] = list(result.scalars().all())

        if not copy_setup_configs:
            logger.debug("No CopySetupConfig's found", extra={"user_id": user_id})

        return copy_setup_configs
    except SQLAlchemyError:
        logger.exception("Database error while fetching CopySetupConfig's", extra={"user_id": user_id})
        raise

