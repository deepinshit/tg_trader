# backend/messages/processing.py

import logging
from typing import Dict, Set

from models import Message, SignalReply
from enums import SignalReplyAction, SignalReplyGeneratedBy
from backend.db.crud.general import create, update
from backend.db.functions import get_session_context
from backend.messages.helpers import get_symbol_map
from backend.extract.functions import get_signal_from_text, get_signal_reply_action_from_text
from backend.distribution.signal_reply import distribute_signal_reply
from backend.distribution.signal import distribute_signal


logger = logging.getLogger(__name__)


async def process_updated_message(message_text: str, original_message: Message) -> None:
    """
    Handle an edited Telegram message.

    Flow:
        1) Clone original message and set the updated text.
        2) Extract a possible Signal from the updated text.
        3) Create or update the related Signal in DB.

    Args:
        message_text: The updated message body (plain text).
        original_message: Original Message ORM/Pydantic model from DB (already persisted).

    Notes:
        - Logging uses `extra` with model ids as <model_name>_id (e.g., message_id, signal_id).
        - Logic/architecture preserved; only defensive checks and consistency improvements.
    """
    if not isinstance(message_text, str) or not message_text.strip():
        logger.debug(
            "Updated message has empty or invalid text. Skipping signal extraction.",
            extra={"message_id": getattr(original_message, "id", None)},
        )
        return

    updated_msg = original_message
    updated_msg.text = message_text


    # Be tolerant if chat/copy_setups is missing/None.
    copy_setups = getattr(getattr(original_message, "tg_chat", None), "copy_setups", None)
    symbols_map: Dict[str, Set[str]] = get_symbol_map(copy_setups)

    try:
        signal = await get_signal_from_text(updated_msg, symbols_map)
    except Exception as e:
        logger.exception(
            "Error extracting signal from updated message.",
            extra={
                "message_id": getattr(original_message, "id", None),
                "error_type": type(e).__name__,
            },
        )
        return

    if not signal:
        logger.debug(
            "No valid signal found in updated message.",
            extra={"message_id": getattr(original_message, "id", None)},
        )
        return

    try:
        async with get_session_context() as session:
            if not getattr(original_message, "signal", None):
                # Create new signal and link to message.
                signal = await create(signal, session)
                original_message.signal_id = signal.id
                await update(original_message, session)
                logger.info(
                    "Signal created from updated message.",
                    extra={
                        "message_id": getattr(original_message, "id", None),
                        "signal_id": getattr(signal, "id", None),
                    },
                )
            else:
                # Update existing related signal with freshly parsed data.
                # Keep the assignment pattern to respect existing architecture.
                original_message.signal = signal
                await update(original_message.signal, session)
                logger.info(
                    "Signal updated from edited message.",
                    extra={
                        "message_id": getattr(original_message, "id", None),
                        "signal_id": getattr(original_message.signal, "id", None),
                    },
                )
    except Exception as e:
        logger.exception(
            "Error saving updated signal to DB.",
            extra={
                "message_id": getattr(original_message, "id", None),
                "signal_id": getattr(getattr(original_message, "signal", None), "id", None),
                "error_type": type(e).__name__,
            },
        )

    logger.info("distributing signal..", extra={
                "message_id": getattr(original_message, "id", None),
                "signal_id": getattr(original_message.signal, "id", None),
            })
    
    try:
        await distribute_signal(signal)
    except Exception as e:
        logger.exception(
            "Error distributing signal.",
            extra={
                "message_id": getattr(original_message, "id", None),
                "signal_id": getattr(original_message.signal, "id", None),
                "error_type": type(e).__name__,
            },
        )


async def process_deleted_message(message: Message) -> None:
    """
    Handle deletion of a Telegram message. If the message had a Signal, auto-generate a CLOSE reply.

    Args:
        message: Deleted Message model from DB.

    Notes:
        - A SignalReply is created with action CLOSE and linked back to the original Signal.
    """
    if not getattr(message, "signal", None):
        logger.info(
            "Deleted message ignored (no signal to close).",
            extra={"message_id": getattr(message, "id", None)},
        )
        return

    signal_reply = SignalReply(
        action=SignalReplyAction.CLOSE,
        generated_by=SignalReplyGeneratedBy.DELETE,
        info_message="Signal message was deleted",
        original_signal_id=message.signal.id,
    )

    try:
        async with get_session_context() as session:
            signal_reply = await create(signal_reply, session)
            message.signal_reply_id = signal_reply.id
            await update(message, session)

        logger.info(
            "Signal closed due to message deletion.",
            extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(message.signal, "id", None),
                "signal_reply_id": getattr(signal_reply, "id", None),
            },
        )
    except Exception as e:
        logger.exception(
            "Error creating close reply after message deletion.",
            extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(message.signal, "id", None),
                "error_type": type(e).__name__,
            },
        )

    logger.info("distributing signal reply..", extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(message.signal, "id", None),
                "signal_reply_id": getattr(signal_reply, "id", None),
            })
    
    try:
        await distribute_signal_reply(signal_reply)
    except Exception as e:
        logger.exception(
            "Error distributing signal reply.",
            extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(message.signal, "id", None),
                "signal_reply_id": getattr(signal_reply, "id", None),
                "error_type": type(e).__name__,
            },
        )



async def process_new_message(message: Message) -> None:
    """
    Process a newly received Telegram message for trading signals.

    Args:
        message: New Message model from DB.
    """
    copy_setups = getattr(getattr(message, "tg_chat", None), "copy_setups", None)
    symbols_map: Dict[str, Set[str]] = get_symbol_map(copy_setups)

    try:
        signal = await get_signal_from_text(message, symbols_map)
    except Exception as e:
        logger.exception(
            "Error extracting signal from new message.",
            extra={
                "message_id": getattr(message, "id", None),
                "error_type": type(e).__name__,
            },
        )
        return

    if not signal:
        logger.debug(
            "No valid signal found in new message.",
            extra={"message_id": getattr(message, "id", None)},
        )
        return

    try:
        async with get_session_context() as session:
            signal = await create(signal, session)
            message.signal_id = signal.id
            await update(message, session)

        logger.info(
            "Signal created from new message.",
            extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(signal, "id", None),
            },
        )
    except Exception as e:
        logger.exception(
            "Error saving signal from new message.",
            extra={
                "message_id": getattr(message, "id", None),
                "error_type": type(e).__name__,
            },
        )

    logger.info("distributing signal reply..", extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(message.signal, "id", None),
            })
    
    try:
        await distribute_signal(signal)
    except Exception as e:
        logger.exception(
            "Error distributing signal reply.",
            extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(message.signal, "id", None),
                "error_type": type(e).__name__,
            },
        )

    


async def process_reply_message(message: Message, reply_to_message: Message) -> None:
    """
    Process a reply message to detect and record signal-reply actions.

    Args:
        message: The reply Message instance (persisted).
        reply_to_message: The original Message being replied to.

    Behavior:
        - If the replied-to message has no Signal, do nothing.
        - Otherwise, extract the reply action and create a SignalReply linked to the Signal.
    """
    if not getattr(reply_to_message, "signal", None):
        logger.info(
            "Reply ignored (original message has no signal).",
            extra={"message_id": getattr(message, "id", None)},
        )
        return

    try:
        action = await get_signal_reply_action_from_text(message, reply_to_message.signal)
    except Exception as e:
        logger.exception(
            "Error extracting reply action from message.",
            extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(reply_to_message.signal, "id", None),
                "error_type": type(e).__name__,
            },
        )
        return

    if action is None:
        logger.info(
            "Reply ignored (no valid reply action).",
            extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(reply_to_message.signal, "id", None),
            },
        )
        return

    signal_reply = SignalReply(
        action=action,
        generated_by=SignalReplyGeneratedBy.REPLY,
        info_message="Reply message",
        original_signal_id=reply_to_message.signal.id,
    )

    try:
        async with get_session_context() as session:
            signal_reply = await create(signal_reply, session)
            message.signal_reply_id = signal_reply.id
            await update(message, session)

        logger.info(
            "Signal reply recorded.",
            extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(reply_to_message.signal, "id", None),
                "signal_reply_id": getattr(signal_reply, "id", None),
            },
        )
    except Exception as e:
        logger.exception(
            "Error saving signal reply.",
            extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(reply_to_message.signal, "id", None),
                "error_type": type(e).__name__,
            },
        )

    logger.info("distributing signal_reply..", extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(reply_to_message.signal, "id", None),
                "signal_reply_id": getattr(signal_reply, "id", None),
            })
    
    try:
        await distribute_signal_reply(signal_reply)
    except Exception as e:
        logger.exception(
            "Error distributing signal reply.",
            extra={
                "message_id": getattr(message, "id", None),
                "signal_id": getattr(reply_to_message.signal, "id", None),
                "error_type": type(e).__name__,
            },
        )