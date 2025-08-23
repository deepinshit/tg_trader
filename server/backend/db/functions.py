# /backend/db/functions.py

"""
Database session utilities and startup/shutdown hooks for SQLAlchemy 2.0 (async).

Features
--------
- Single async engine (create_async_engine) with robust pool settings.
- Async session factory (sessionmaker) with expire_on_commit=False.
- async context manager `get_session()` that commits on success and rolls back on error.
- Sync ORM event listener that updates `TgChat.updated_at` whenever new `Message`s are flushed.
- Optional table creation on startup (use Alembic in real production).
- Safe, defensive handling for database URL → ensures async driver is used.

Usage
-----
from backend.db.functions import get_session, setup_db, dispose_engine

async with get_session_context() as session:
    ...

Call setup_db() once at app startup; call dispose_engine() on shutdown.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Iterable, Set

from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session as SyncSession
from sqlalchemy.orm import sessionmaker

from helpers import utc_now
from models import Base, Message, TgChat  # <- Base is DeclarativeBase in your SQLAlchemy 2.0 models
from cfg import DATABASE_URL  # e.g. "postgresql://user:pass@host:5432/dbname"

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _to_async_url(url: str) -> str:
    """
    Convert a common sync SQLAlchemy URL to its async variant if needed.
    - Postgres: psycopg2/psycopg → asyncpg/psycopg_async
    - MySQL:    pymysql → aiomysql
    - SQLite:   sqlite → sqlite+aiosqlite
    If the URL already looks async, it is returned unchanged.
    """
    if "+async" in url or "+asyncpg" in url or "+aiomysql" in url or "+aiosqlite" in url:
        return url

    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+psycopg_async://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)

    if url.startswith("mysql+pymysql://"):
        return url.replace("mysql+pymysql://", "mysql+aiomysql://", 1)

    if url.startswith("sqlite:///") or url.startswith("sqlite:///:memory:"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)

    # Unknown or already async driver—return as is.
    return url


# --------------------------------------------------------------------------------------
# Engine & Session Factory
# --------------------------------------------------------------------------------------

_async_database_url = _to_async_url(DATABASE_URL)

_engine_options = {
    "echo": False,          # leave False in prod; rely on structured logging
    "future": True,         # SQLAlchemy 2.0 style
    "pool_pre_ping": True,  # avoid stale connections
    "pool_recycle": 1800,   # 30 minutes; tune per infra
    # You may set pool_size / max_overflow explicitly in high-traffic deployments:
    # "pool_size": 5,
    # "max_overflow": 10,
}

engine: AsyncEngine = create_async_engine(_async_database_url, **_engine_options)

# expire_on_commit=False ⇒ attributes remain accessible after commit (common for APIs)
async_session_factory: sessionmaker[AsyncSession] = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Prevent duplicate listener registration (e.g., dev autoreload)
_LISTENERS_ADDED = False


async def _session_generator() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# For FastAPI (Depends)
get_session = _session_generator

# For async with
@asynccontextmanager
async def get_session_context() -> AsyncIterator[AsyncSession]:
    async for session in _session_generator():
        yield session

# --------------------------------------------------------------------------------------
# Event Listeners
# --------------------------------------------------------------------------------------

def _add_db_listeners() -> None:
    """
    Register SQLAlchemy ORM event listeners.

    Notes:
    - Listeners are registered on the *sync* Session class. ORM events run in sync
      context even when using AsyncSession, so the function must be sync.
    - We use a Core UPDATE inside after_flush to avoid creating ORM instances
      (no autoflush re-entry / infinite loops) and to keep it in the same transaction.
    """
    global _LISTENERS_ADDED
    if _LISTENERS_ADDED:
        return

    @event.listens_for(SyncSession, "after_flush")
    def _after_flush_message(session: SyncSession, ctx) -> None:
        # Collect new Message instances per flush and deduplicate chat IDs.
        new_objs: Iterable[object] = session.new or ()
        chat_ids: Set[int] = set()

        for obj in new_objs:
            if isinstance(obj, Message):
                tg_chat_id = getattr(obj, "tg_chat_id", None)
                if tg_chat_id is not None:
                    # Ensure int to match PK type and avoid surprises
                    chat_ids.add(int(tg_chat_id))

        if not chat_ids:
            return

        stmt = (
            update(TgChat)
            .where(TgChat.id.in_(chat_ids))
            .values(updated_at=utc_now())
        )
        session.execute(stmt)
        # Do not commit here; this runs inside the ongoing transaction.

    _LISTENERS_ADDED = True
    logger.debug("Database event listeners registered.")


# --------------------------------------------------------------------------------------
# Setup / Lifecycle
# --------------------------------------------------------------------------------------

async def setup_db() -> None:
    """
    Prepare the database layer. Call once at application startup.

    - Optionally create tables if `CREATE_TABLES_ON_STARTUP` env var is truthy.
      (Recommended to use Alembic for real migrations in production.)
    - Register event listeners.
    """
    create_on_startup = os.getenv("CREATE_TABLES_ON_STARTUP", "true").lower() in {"1", "true", "yes", "on"}

    if create_on_startup:
        async with engine.begin() as conn:
            # Run DDL in sync context safely
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ensured (create_all).")

    _add_db_listeners()

    logger.info("Database setup complete. Listeners active.")

async def dispose_engine() -> None:
    """
    Dispose of the engine and close all pooled connections. Call on graceful shutdown.
    """
    await engine.dispose()
    logger.debug("Database engine disposed.")


__all__ = [
    "engine",
    "get_session",
    "setup_db",
    "dispose_engine",
    "async_session_factory",
]
