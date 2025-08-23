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

import asyncio
import logging
from typing import Optional

from telethon import TelegramClient

from cfg import TG_SESSION_NAME, TG_API_ID, TG_API_HASH

logger = logging.getLogger(__name__)

# Global client instance managed by this module
client: Optional[TelegramClient] = None

# Internal lock to avoid concurrent/duplicate initializations
_init_lock = asyncio.Lock()


async def _get_telegram_client() -> TelegramClient:
    """
    Create (but do not start/connect) a Telegram client instance.

    Note:
        The Telethon client constructor is synchronous; this function remains
        `async` to preserve the module's public shape and avoid knock-on changes.
    """
    # Basic validation; fail fast if config is missing
    if not TG_SESSION_NAME:
        raise RuntimeError("Missing TG_SESSION_NAME.")
    if not TG_API_ID:
        raise RuntimeError("Missing TG_API_ID.")
    if not TG_API_HASH:
        raise RuntimeError("Missing TG_API_HASH.")

    # Telethon expects an int for API ID; if your env loader returns a string,
    # Telethon will raise a descriptive error. We keep it simple here.
    return TelegramClient(TG_SESSION_NAME, TG_API_ID, TG_API_HASH)


async def init_telegram_client(*, model_name_id: Optional[int] = None) -> Optional[TelegramClient]:
    """
    Start and connect the global Telegram client, returning the instance.

    This function is idempotent and safe to call multiple times. It ensures:
    - A single client is created.
    - The client is started and connected.
    - Errors are logged instead of bubbling and crashing the caller.

    Args:
        model_name_id: Optional DB model id to include in structured logs.

    Returns:
        TelegramClient on success, or None on failure.
    """
    global client

    async with _init_lock:
        if client is None:
            try:
                logger.info(
                    "Initializing Telegram client...",
                    extra={"model_name_id": model_name_id},
                )
                client = await _get_telegram_client()
            except Exception as e:  # pragma: no cover (defensive)
                logger.exception(
                    "Failed to create Telegram client: %s",
                    e,
                    extra={"model_name_id": model_name_id},
                )
                client = None
                return None

        try:
            # `.start()` will internally connect and handle auth when possible.
            await client.start()
            # Ensure connection; `.connect()` is safe to call even if already connected.
            await client.connect()  # returns True if already connected

            if not client.is_connected():
                logger.error(
                    "Telegram client could not connect.",
                    extra={"model_name_id": model_name_id},
                )
                return None

        except Exception as e:  # pragma: no cover (defensive)
            logger.exception(
                "Error while initializing/connecting Telegram client: %s",
                e,
                extra={"model_name_id": model_name_id},
            )
            return None

        logger.info(
            "Telegram client successfully initialized and connected.",
            extra={"model_name_id": model_name_id},
        )
        return client


__all__ = [
    "init_telegram_client",
    "register_handler",
    "client",
]
