# backend/messages/tg/handlers.py

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
from backend.db.crud.message import get_message_on_tg_chat_and_msg_id
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

    try:
        async with get_session_context() as session:
            async with session.begin():
                tg_chat = await get_tg_chat_on_id(session, event.chat_id)
                if not tg_chat:
                    logger.warning("No TgChat found for message edited event.", extra={"tg_chat_id": event.chat_id})
                    return

                original_message = await get_message_on_tg_chat_and_msg_id(session, tg_chat.id, tg_message.id)
                post_datetime = tg_message.date.replace(tzinfo=timezone.utc) if tg_message.date.tzinfo is None else tg_message.date.astimezone(timezone.utc)

                if original_message is None:
                    message = Message(
                        tg_chat_id=tg_chat.id,
                        tg_msg_id=tg_message.id,
                        text=msg_text,
                        post_datetime=post_datetime.replace(tzinfo=None),
                        tg_chat=tg_chat,
                    )
                    message = await session.merge(message)
                    logger.info(
                        "Created message due to edit event (message not found previously).",
                        extra={"tg_chat_id": tg_chat.id},
                    )
                    signal = await process_new_message(message, session)
                    # distribute new signal
                    try:
                        await distribute_signal(signal)
                        logger.info("Signal distributed.", extra={"message_id": message.id, "signal_id": signal.id})
                    except Exception as e:
                        logger.exception("Error distributing signal", extra={"message_id": message.id, "signal_id": signal.id})
                else:
                    signal, _ = await process_updated_message(msg_text, original_message, session)
                    try:
                        if signal:
                            await distribute_signal(signal)
                            logger.info("Updated signal distributed.", extra={"message_id": original_message.id, "signal_id": signal.id})
                    except Exception as e:
                        logger.exception("Error distributing updated signal", extra={"message_id": original_message.id, "signal_id": signal.id})

    except Exception as e:
        logger.exception("Error handling message edited event.", extra={"tg_chat_id": event.chat_id})


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
                        signal_reply = await process_deleted_message(deleted_message, session)
                        # distribute signal reply
                        try:
                            await distribute_signal_reply(signal_reply)
                            logger.info("Signal reply distributed.", extra={"message_id": deleted_message.id, "signal_reply_id": signal_reply.id})
                        except Exception as e:
                            logger.exception("Error distributing signal reply", extra={"message_id": deleted_message.id, "signal_reply_id": signal_reply.id})

    except Exception as e:
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

    message: Optional[Message] = None
    reply_to_message: Optional[Message] = None

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

                post_datetime = tg_message.date.replace(tzinfo=timezone.utc) if tg_message.date.tzinfo is None else tg_message.date.astimezone(timezone.utc)
                message = Message(
                    tg_msg_id=tg_message.id,
                    tg_chat_id=tg_chat.id,
                    text=msg_text,
                    post_datetime=post_datetime.replace(tzinfo=None),
                    tg_chat=tg_chat,
                )
                session.add(message)
                await session.flush()

                if tg_message.reply_to and getattr(tg_message.reply_to, "reply_to_msg_id", None):
                    reply_to_message = await get_message_on_tg_chat_and_msg_id(session, tg_chat.id, tg_message.reply_to.reply_to_msg_id)

    except Exception as e:
        logger.exception("Error preparing new message event.", extra={"tg_chat_id": getattr(event, "chat_id", None)})
        return

    try:
        if message:
            if reply_to_message:
                signal_reply = await process_reply_message(message, reply_to_message, session)
                try:
                    await distribute_signal_reply(signal_reply)
                    logger.info("Reply signal distributed.", extra={"message_id": message.id, "signal_reply_id": signal_reply.id})
                except Exception as e:
                    logger.exception("Error distributing reply signal", extra={"message_id": message.id, "signal_reply_id": signal_reply.id})
            else:
                signal = await process_new_message(message, session)
                try:
                    await distribute_signal(signal)
                    logger.info("New signal distributed.", extra={"message_id": message.id, "signal_id": signal.id})
                except Exception as e:
                    logger.exception("Error distributing new signal", extra={"message_id": message.id, "signal_id": signal.id})

    except Exception as e:
        logger.exception("Error processing new/reply message.", extra={"tg_chat_id": getattr(event, "chat_id", None), "message_id": getattr(message, "id", None)})


def register_handlers(client: TelegramClient) -> None:
    client.add_event_handler(new_message_event_handler, NewMessage)
    client.add_event_handler(message_edited_event_handler, MessageEdited)
    client.add_event_handler(message_deleted_event_handler, MessageDeleted)
    logger.info("Telegram event handlers registered.")
