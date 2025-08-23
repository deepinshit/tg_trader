# backend/messages/tg/handlers.py

import logging
from typing import List, Optional
from datetime import timezone

from sqlalchemy.exc import IntegrityError
from telethon import TelegramClient, types
from telethon.events.newmessage import NewMessage
from telethon.events.messageedited import MessageEdited
from telethon.events.messagedeleted import MessageDeleted
from telethon.tl.custom.chatgetter import ChatGetter

from models import CopySetup, Message, TgChat
from backend.db.crud.tg_chat import get_tg_chat_on_id
from backend.db.crud.message import get_message_on_tg_chat_and_msg_id
from backend.db.crud.general import create
from backend.db.functions import get_session_context
from backend.messages.helpers import filter_message_text, build_tg_chat
from backend.messages.processing import (
    process_new_message,
    process_deleted_message,
    process_reply_message,
    process_updated_message,
)

logger = logging.getLogger(__name__)

__all__ = [
    "message_edited_event_handler",
    "message_deleted_event_handler",
    "new_message_event_handler",
    "register_handlers",
]


async def message_edited_event_handler(event: MessageEdited.Event) -> None:
    """
    Handle Telegram 'message edited' events.

    Steps:
        1. Skip if chat_id is missing.
        2. Filter message text.
        3. Retrieve TgChat.
        4. Retrieve or create Message.
        5. Process as new or updated message.

    Notes:
        - Logging `extra` includes `tg_chat_id` and, where applicable, `message_id`.
        - Error logs include `error_type` for easier aggregation.
    """
    if not event.chat_id:
        logger.debug("Skipped message edited event without chat_id.")
        return

    tg_message: types.Message = event.message
    msg_text = await filter_message_text(tg_message.message)
    if msg_text is None:
        logger.info(
            "Message filtered out (empty or invalid).",
            extra={"tg_chat_id": event.chat_id},
        )
        return

    try:
        async with get_session_context() as session:
            tg_chat = await get_tg_chat_on_id(session, event.chat_id)
            if tg_chat is None:
                logger.warning(
                    "No tg_chat found for message edited event.",
                    extra={"tg_chat_id": event.chat_id},
                )
                return
            
            if not any(cs.active for cs in tg_chat.copy_setups):
                logger.debug(
                    "No active copy_setups for chat.",
                    extra={"tg_chat_id": tg_chat.id},
                )
                return

            original_message = await get_message_on_tg_chat_and_msg_id(
                session, tg_chat.id, tg_message.id
            )

            if original_message is None:
                # Normalize to UTC; handle naive & aware datetimes safely
                post_datetime = (
                    tg_message.date.replace(tzinfo=timezone.utc)
                    if tg_message.date.tzinfo is None
                    else tg_message.date.astimezone(timezone.utc)
                )

                # First time we see this message: create and process as new.
                message = Message(
                    tg_chat_id=tg_chat.id,
                    tg_msg_id=tg_message.id,
                    text=msg_text,
                    post_datetime=post_datetime.replace(tzinfo=None)
                )
                message = await create(message, session)
                logger.info(
                    "Created message due to edit event (message not found previously).",
                    extra={"tg_chat_id": tg_chat.id, "message_id": message.id},
                )
                await process_new_message(message)
            else:
                logger.info(
                    "Processing updated (edited) message.",
                    extra={"tg_chat_id": tg_chat.id, "message_id": original_message.id},
                )
                await process_updated_message(msg_text, original_message)

    except Exception as e:
        logger.exception(
            "Unexpected error while handling message edited event.",
            extra={
                "tg_chat_id": event.chat_id,
                "error_type": type(e).__name__,
            },
        )


async def message_deleted_event_handler(event: MessageDeleted.Event) -> None:
    """
    Handle Telegram 'message deleted' events.

    Steps:
        1. Skip if chat_id is missing.
        2. Retrieve TgChat.
        3. Process deletion for each message ID in event.deleted_ids.

    Notes:
        - Logging `extra` includes `tg_chat_id` and `message_id` (DB model).
    """
    if not event.chat_id:
        logger.debug("Skipped message deleted event without chat_id.")
        return

    tg_chat: Optional[TgChat] = None
    try:
        async with get_session_context() as session:
            tg_chat = await get_tg_chat_on_id(session, event.chat_id)
            if tg_chat is None:
                logger.warning(
                    "No tg_chat found for message deleted event.",
                    extra={"tg_chat_id": event.chat_id},
                )
                return

        # Process each deleted Telegram message id
        for tg_msg_id in list(getattr(event, "deleted_ids", []) or []):
            deleted_message: Optional[Message] = None
            try:
                async with get_session_context() as session:
                    # Use internal tg_chat.id (DB ID), not event.chat_id (Telegram ID)
                    deleted_message = await get_message_on_tg_chat_and_msg_id(
                        session, tg_chat.id, tg_msg_id
                    )
            except Exception as e:
                logger.exception(
                    "Error fetching message to delete.",
                    extra={
                        "tg_chat_id": tg_chat.id,
                        "error_type": type(e).__name__,
                    },
                )

            if deleted_message:
                try:
                    logger.info(
                        "Processing deleted message.",
                        extra={
                            "tg_chat_id": tg_chat.id,
                            "message_id": deleted_message.id,
                        },
                    )
                    await process_deleted_message(deleted_message)
                except Exception as e:
                    logger.exception(
                        "Error processing deleted message.",
                        extra={
                            "tg_chat_id": tg_chat.id,
                            "message_id": deleted_message.id,
                            "error_type": type(e).__name__,
                        },
                    )
            else:
                logger.debug(
                    "Message delete event did not match any stored message.",
                    extra={"tg_chat_id": tg_chat.id, "tg_msg_id": tg_msg_id},
                )

    except Exception as e:
        logger.exception(
            "Error while handling message deleted event.",
            extra={
                "tg_chat_id": getattr(tg_chat, "id", event.chat_id),
                "error_type": type(e).__name__,
            },
        )


async def new_message_event_handler(event: NewMessage.Event) -> None:
    """
    Handle Telegram 'new message' events.

    Steps:
        1. Skip if chat_id is missing.
        2. Filter message text.
        3. Retrieve TgChat (with copy_setups) or create it.
        4. Skip if no active copy_setups.
        5. Create Message.
        6. Process as new or reply message.

    Notes:
        - Logging `extra` includes `tg_chat_id` and, where applicable, `message_id`.
        - Timezone is normalized to UTC for persistence.
    """
    if not event.chat_id:
        logger.debug("Skipped new message event without chat_id.")
        return

    tg_message: types.Message = event.message
    msg_text = await filter_message_text(tg_message.message)
    if msg_text is None:
        logger.info(
            "Message filtered out (empty or invalid).",
            extra={"tg_chat_id": event.chat_id},
        )
        return

    tg_chat: Optional[TgChat] = None
    message: Optional[Message] = None
    reply_to_message: Optional[Message] = None

    try:
        async with get_session_context() as session:
            tg_chat = await get_tg_chat_on_id(session, event.chat_id)

            if not tg_chat:
                chat = await event.get_chat()
                try:
                    tg_chat = await create(build_tg_chat(chat, chat_id=event.chat_id), session)
                except IntegrityError:
                    await session.rollback()
                    tg_chat = await get_tg_chat_on_id(session, event.chat_id)

            if not any(cs.active for cs in tg_chat.copy_setups):
                logger.debug(
                    "No active copy_setups for chat.",
                    extra={"tg_chat_id": tg_chat.id},
                )
                return

            # Normalize to UTC; handle naive & aware datetimes safely
            post_datetime = (
                tg_message.date.replace(tzinfo=timezone.utc)
                if tg_message.date.tzinfo is None
                else tg_message.date.astimezone(timezone.utc)
            )

            message = Message(
                tg_msg_id=tg_message.id,
                tg_chat_id=tg_chat.id,
                text=msg_text,
                post_datetime=post_datetime.replace(tzinfo=None),
            )
            # Avoid extra DB roundtrips in processing when tg_chat is needed
            message.tg_chat = tg_chat

            # If this is a reply, try to locate the parent message in our DB
            if tg_message.reply_to and getattr(tg_message.reply_to, "reply_to_msg_id", None):
                reply_to_message = await get_message_on_tg_chat_and_msg_id(
                    session,
                    tg_chat.id,
                    tg_message.reply_to.reply_to_msg_id,
                )

    except Exception as e:
        logger.exception(
            "Error while preparing new message event.",
            extra={
                "tg_chat_id": getattr(tg_chat, "id", event.chat_id),
                "error_type": type(e).__name__,
            },
        )
        return

    try:
        if reply_to_message is not None:
            logger.info(
                "Processing reply message.",
                extra={
                    "tg_chat_id": tg_chat.id,
                    # message.id may not exist yet if persistence occurs in processing
                    "message_id": getattr(message, "id", None),
                },
            )
            await process_reply_message(message, reply_to_message)
        else:
            logger.info(
                "Processing new message.",
                extra={
                    "tg_chat_id": tg_chat.id,
                    "message_id": getattr(message, "id", None),
                },
            )
            await process_new_message(message)
    except Exception as e:
        logger.exception(
            "Error processing new/reply message.",
            extra={
                "tg_chat_id": tg_chat.id,
                "message_id": getattr(message, "id", None),
                "error_type": type(e).__name__,
            },
        )


def register_handlers(client: TelegramClient) -> None:
    """
    Register Telegram event handlers with the provided client.
    """
    client.add_event_handler(new_message_event_handler, NewMessage)
    client.add_event_handler(message_edited_event_handler, MessageEdited)
    client.add_event_handler(message_deleted_event_handler, MessageDeleted)
    logger.info("Telegram event handlers registered.")
