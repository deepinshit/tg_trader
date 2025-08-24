# backend/messages/processing.py

import logging
from typing import Dict, Set, Tuple, Optional

from models import Message, SignalReply, Signal
from enums import SignalReplyAction, SignalReplyGeneratedBy
from backend.db.crud.general import create, update
from backend.db.functions import AsyncSession
from backend.messages.helpers import get_symbol_map
from backend.extract.functions import get_signal_from_text, get_signal_reply_action_from_text

logger = logging.getLogger(__name__)


async def process_updated_message(
    message_text: str,
    original_message: Message,
    session: AsyncSession
) -> Tuple[Optional[Signal], Optional[SignalReply]]:
    """
    Handle an edited Telegram message.

    Returns:
        Tuple[Optional[Signal], Optional[SignalReply]]: The updated/created Signal and SignalReply.
    Raises:
        ValueError: if message text is invalid or no signal is extracted.
        Exception: for DB errors or other unexpected failures.
    """
    if not message_text or not message_text.strip():
        raise ValueError("Updated message text is empty or invalid")

    original_message.text = message_text
    copy_setups = getattr(getattr(original_message, "tg_chat", None), "copy_setups", None)
    symbols_map: Dict[str, Set[str]] = get_symbol_map(copy_setups)

    signal = await get_signal_from_text(original_message, symbols_map)
    if not signal:
        raise ValueError("No valid signal found in updated message")

    if not getattr(original_message, "signal", None):
        # New signal
        signal = await create(signal, session)
        original_message.signal_id = signal.id
    else:
        # Update existing
        signal = await update(signal, session)
        original_message.signal = signal

    await update(original_message, session)
    return signal, None


async def process_deleted_message(
    message: Message,
    session: AsyncSession
) -> SignalReply:
    """
    Handle deletion of a Telegram message.

    Returns:
        SignalReply: The generated CLOSE reply.
    Raises:
        ValueError: if message has no associated Signal.
        Exception: for DB errors.
    """
    if not getattr(message, "signal", None):
        raise ValueError("Deleted message has no associated signal")

    signal_reply = SignalReply(
        action=SignalReplyAction.CLOSE,
        generated_by=SignalReplyGeneratedBy.DELETE,
        info_message="Signal message was deleted",
        original_signal_id=message.signal.id,
    )

    signal_reply = await create(signal_reply, session)
    message.signal_reply_id = signal_reply.id
    await update(message, session)
    return signal_reply


async def process_new_message(
    message: Message,
    session: AsyncSession
) -> Signal:
    """
    Process a newly received Telegram message for trading signals.

    Returns:
        Signal: The created signal.
    Raises:
        ValueError: if no valid signal is extracted.
        Exception: for DB errors.
    """
    copy_setups = getattr(getattr(message, "tg_chat", None), "copy_setups", None)
    symbols_map: Dict[str, Set[str]] = get_symbol_map(copy_setups)

    signal = await get_signal_from_text(message, symbols_map)
    if not signal:
        raise ValueError("No valid signal found in new message")

    signal = await create(signal, session)
    message.signal_id = signal.id
    await update(message, session)
    return signal


async def process_reply_message(
    message: Message,
    reply_to_message: Message,
    session: AsyncSession
) -> SignalReply:
    """
    Process a reply message to detect and record signal-reply actions.

    Returns:
        SignalReply: The created signal reply.
    Raises:
        ValueError: if original message has no signal or reply action cannot be determined.
        Exception: for DB errors.
    """
    if not getattr(reply_to_message, "signal", None):
        raise ValueError("Original message has no associated signal")

    action = await get_signal_reply_action_from_text(message, reply_to_message.signal)
    if action is None:
        raise ValueError("No valid reply action extracted from reply message")

    signal_reply = SignalReply(
        action=action,
        generated_by=SignalReplyGeneratedBy.REPLY,
        info_message="Reply message",
        original_signal_id=reply_to_message.signal.id,
    )

    signal_reply = await create(signal_reply, session)
    message.signal_reply_id = signal_reply.id
    await update(message, session)
    return signal_reply
