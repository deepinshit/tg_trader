# backend/messages/tg/client.py

"""
Initialize the Telegram client and register event handlers.

Design goals:
- Production-ready, robust, and simple.
- No architectural shifts; minimal, safe improvements only.
- Clear type hints and documentation.
- Defensive checks around env/config and connection state.
- Task-wrapped handlers with error capturing, so background exceptions are logged.
- Logging supports `extra={"model_name_id": <id>}` when available.
"""

from __future__ import annotations

import inspect
import logging
from typing import Awaitable, Callable, Optional, Any

from telethon import TelegramClient
from telethon.utils import get_peer_id
from sqlalchemy.exc import IntegrityError

from background_tasks import create_background_task
from backend.db.functions import get_session_context
from backend.db.crud.general import create
from backend.db.crud.tg_chat import get_tg_chat_on_id
from backend.messages.helpers import build_tg_chat

logger = logging.getLogger(__name__)

async def _run_handler_safely(
    handler: Callable[[Any], Awaitable[None]],
    event: Any
) -> None:
    """Execute a handler with robust error logging."""
    try:
        await handler(event)
    except Exception:
        logger.exception(
            "Unhandled exception in Telegram event handler."
        )


async def register_handler(
    handler: Callable[[Any], Awaitable[None]],
    tg_client: Optional[TelegramClient],
    *,
    event_type: Any,
) -> bool:
    """
    Register an event handler with the Telegram client.

    The handler is wrapped so it runs as a background task and any exceptions
    are captured and logged (preventing 'Task exception was never retrieved').

    Args:
        handler: An async function taking a single `event` argument.
        tg_client: Optional explicit client. If not provided, uses the global client.
        event_type: The Telethon event builder (e.g., `events.NewMessage(...)`).
        model_name_id: Optional DB model id to include in structured logs.

    Returns:
        True if the handler was registered, False otherwise.
    """
    # Resolve client
    tg_client

    if not tg_client.is_connected():
        logger.error(
            "Cannot register handler: Telegram client is not connected."
        )
        return False

    # Enforce an async handler to match how we schedule it
    if not inspect.iscoroutinefunction(handler):
        logger.error(
            "Handler must be an async function (got %r).",
            handler,
        )
        return False

    try:
        # Wrap to ensure exceptions are logged within the task
        async def _callback(ev: Any) -> None:
            create_background_task(
                _run_handler_safely(
                    handler, ev
                ), name=f"Telegram {type(ev)} handling"
            )

        tg_client.add_event_handler(_callback, event_type)
        logger.info(
            "Telegram handler registered."
        )
        return True
    except Exception:
        logger.exception(
            "Failed to register Telegram handler."
        )
        return False
    
async def update_dialogs(client: TelegramClient, limit=None):
    """
    Fetch all dialogs (chats) from Telegram and convert them into TgChat models.
    """
    counter = 0
    async with get_session_context() as session:
        try:
            async for dialog in client.iter_dialogs(limit=limit):
                counter += 1
                logger.debug(f"{counter} ensuring chat in db")
                chat = dialog.entity
                chat_id = get_peer_id(chat)
                try:
                    tg_chat = await get_tg_chat_on_id(session, chat_id)
                    if not tg_chat:
                        try:
                            tg_chat = await create(build_tg_chat(chat, chat_id=chat_id), session)
                        except IntegrityError:
                            await session.rollback()
                except Exception as e:
                    # protect against a single chat breaking everything
                    logger.warning(f"Failed to build TgChat for chat_id={getattr(chat, 'id', None)}: {e}")
                    
        except Exception as e:
            logger.exception("unexcpected error while ensuring all tg chats are in db", extra={"error_type": type(e)})


__all__ = [
    "init_telegram_client",
    "register_handler",
    "client",
]
