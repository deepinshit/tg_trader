import logging
from typing import Optional
from datetime import timezone

from sqlalchemy.exc import IntegrityError
from telethon import TelegramClient, types
from telethon.events.newmessage import NewMessage
from telethon.events.messageedited import MessageEdited
from telethon.events.messagedeleted import MessageDeleted

from models import Message, TgChat
from backend.db.crud.tg_chat import get_tg_chat_on_id
from backend.db.crud.message import get_message_on_tg_chat_and_msg_id, create_or_get_message
from backend.db.functions import get_session_context
from backend.messages.helpers import filter_message_text, build_tg_chat
from backend.messages.processing import (
    process_new_message,
    process_deleted_message,
    process_reply_message,
    process_updated_message,
)
from backend.distribution.signal import distribute_signal
from backend.distribution.signal_reply import distribute_signal_reply

logger = logging.getLogger(__name__)


async def message_edited_event_handler(event: MessageEdited.Event) -> None:
    if not event.chat_id:
        logger.debug("Skipped message edited event without chat_id.")
        return

    tg_message: types.Message = event.message
    msg_text = await filter_message_text(tg_message.message)
    if not msg_text:
        logger.info("Message filtered out (empty or invalid).", extra={"tg_chat_id": event.chat_id})
        return

    signal, signal_reply = None, None

    try:
        async with get_session_context() as session:
            async with session.begin():
                tg_chat = await get_tg_chat_on_id(session, event.chat_id)
                if not tg_chat:
                    logger.warning("No TgChat found for message edited event.", extra={"tg_chat_id": event.chat_id})
                    return

                original_message = await get_message_on_tg_chat_and_msg_id(session, tg_chat.id, tg_message.id)
                post_datetime = (
                    tg_message.date.replace(tzinfo=timezone.utc)
                    if tg_message.date.tzinfo is None
                    else tg_message.date.astimezone(timezone.utc)
                )

                if original_message is None:
                    message = await create_or_get_message(
                        session=session,
                        tg_chat_id=tg_chat.id,
                        tg_msg_id=tg_message.id,
                        text=msg_text,
                        post_datetime=post_datetime.replace(tzinfo=None),
                        tg_chat=tg_chat,
                    )
                    try:
                        signal, signal_reply = await process_new_message(message, session)
                    except ValueError as e:
                        logger.debug(f"New message not processed: {str(e)}", extra={"message_id": message.id})
                        return
                else:
                    try:
                        signal, signal_reply = await process_updated_message(msg_text, original_message, session)
                    except ValueError as e:
                        logger.debug(f"Updated message not processed: {str(e)}", extra={"message_id": original_message.id})
                        return
    except Exception:
        logger.exception("Error handling message edited event.", extra={"tg_chat_id": getattr(event, "chat_id", None)})
        return

    # Distribution outside session
    try:
        if signal:
            await distribute_signal(signal)
        if signal_reply:
            await distribute_signal_reply(signal_reply)
    except Exception:
        logger.exception("Error distributing signal or signal reply.", extra={"tg_chat_id": getattr(event, "chat_id", None)})


async def message_deleted_event_handler(event: MessageDeleted.Event) -> None:
    if not event.chat_id:
        logger.debug("Skipped message deleted event without chat_id.")
        return

    try:
        async with get_session_context() as session:
            async with session.begin():
                tg_chat = await get_tg_chat_on_id(session, event.chat_id)
                if not tg_chat:
                    logger.warning("No TgChat found for message deleted event.", extra={"tg_chat_id": event.chat_id})
                    return

                for tg_msg_id in getattr(event, "deleted_ids", []) or []:
                    deleted_message = await get_message_on_tg_chat_and_msg_id(session, tg_chat.id, tg_msg_id)
                    if deleted_message:
                        try:
                            signal_reply = await process_deleted_message(deleted_message, session)
                        except ValueError as e:
                            logger.debug(f"Deleted message skipped: {str(e)}", extra={"message_id": tg_msg_id})
                            continue

                        # Distribution outside session
                        try:
                            await distribute_signal_reply(signal_reply)
                        except Exception:
                            logger.exception(
                                "Error distributing signal reply from deleted message.",
                                extra={"message_id": tg_msg_id},
                            )
    except Exception:
        logger.exception("Error handling message deleted event.", extra={"tg_chat_id": getattr(event, "chat_id", None)})


async def new_message_event_handler(event: NewMessage.Event) -> None:
    if not event.chat_id:
        logger.debug("Skipped new message event without chat_id.")
        return

    tg_message: types.Message = event.message
    msg_text = await filter_message_text(tg_message.message)
    if not msg_text:
        logger.info("Message filtered out (empty or invalid).", extra={"tg_chat_id": event.chat_id})
        return

    signal, signal_reply = None, None

    try:
        async with get_session_context() as session:
            async with session.begin():
                tg_chat = await get_tg_chat_on_id(session, event.chat_id)
                if not tg_chat:
                    chat = await event.get_chat()
                    try:
                        tg_chat = build_tg_chat(chat, chat_id=event.chat_id)
                        session.add(tg_chat)
                        await session.flush()
                    except IntegrityError:
                        await session.rollback()
                        tg_chat = await get_tg_chat_on_id(session, event.chat_id)

                post_datetime = (
                    tg_message.date.replace(tzinfo=timezone.utc)
                    if tg_message.date.tzinfo is None
                    else tg_message.date.astimezone(timezone.utc)
                )

                message = await create_or_get_message(
                    session=session,
                    tg_chat_id=tg_chat.id,
                    tg_msg_id=tg_message.id,
                    text=msg_text,
                    post_datetime=post_datetime.replace(tzinfo=None),
                    tg_chat=tg_chat,
                )

                reply_to_message = None
                if tg_message.reply_to and getattr(tg_message.reply_to, "reply_to_msg_id", None):
                    reply_to_message = await get_message_on_tg_chat_and_msg_id(
                        session, tg_chat.id, tg_message.reply_to.reply_to_msg_id
                    )

                if reply_to_message and reply_to_message.signal:
                    try:
                        signal, signal_reply = await process_reply_message(message, reply_to_message, session)
                    except ValueError as e:
                        logger.debug(f"Reply message not processed: {str(e)}", extra={"message_id": message.id})
                        return
                else:
                    try:
                        signal, signal_reply = await process_new_message(message, session)
                    except ValueError as e:
                        logger.debug(f"New message not processed: {str(e)}", extra={"message_id": message.id})
                        return
    except Exception:
        logger.exception("Error handling new message event.", extra={"tg_chat_id": getattr(event, "chat_id", None)})
        return

    # Distribution outside session
    try:
        if signal:
            await distribute_signal(signal)
        if signal_reply:
            await distribute_signal_reply(signal_reply)
    except Exception:
        logger.exception("Error distributing signal or signal reply.", extra={"tg_chat_id": getattr(event, "chat_id", None)})


def register_handlers(client: TelegramClient) -> None:
    client.add_event_handler(new_message_event_handler, NewMessage)
    client.add_event_handler(message_edited_event_handler, MessageEdited)
    client.add_event_handler(message_deleted_event_handler, MessageDeleted)
    logger.info("Telegram event handlers registered.")
