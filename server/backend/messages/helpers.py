# backend/messages/helpers.py

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Dict, List, Optional, Set, Union

from telethon.tl.custom.chatgetter import ChatGetter
from telethon.tl.types import Channel, Chat, User
from telethon.utils import get_peer_id

from cfg_data import SYMBOL_NAMES, SYMBOL_SYNONYMS
from models import CopySetup, TgChat
from enums import TgChatType

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Module constants                                                            #
# --------------------------------------------------------------------------- #

TEXT_MIN_LEN: int = 4
TEXT_MAX_LEN: int = 2000


# --------------------------------------------------------------------------- #
# Utilities                                                                   #
# --------------------------------------------------------------------------- #

def _encode_clean(text: Optional[str]) -> str:
    """
    Normalize text to a safe ASCII-representable form and strip common noise.

    - Replaces non-ASCII characters with '?' via 'errors=\"replace\"'
    - Strips leading/trailing whitespace
    - Removes carriage returns (\\r), keeps newlines
    """
    return (text or "").encode("ascii", errors="replace").decode().strip().replace("\r", "")


# --------------------------------------------------------------------------- #
# Message text filtering                                                      #
# --------------------------------------------------------------------------- #

async def filter_message_text(msg_text: str) -> Optional[str]:
    """
    Validate and normalize a raw message string.

    Returns:
        - Cleaned string if it meets basic length constraints
        - None if empty/invalid/out of bounds

    Constraints are intentionally simple and fast; business logic lives elsewhere.
    """
    # Be defensive against non-string inputs without changing the signature.
    if not isinstance(msg_text, str):
        logger.debug("filter_message_text: non-string input ignored", extra={"model_name_id": None})
        return None

    text = msg_text.strip()
    if not text:
        return None

    # Respect original bounds (do not change behavior).
    if len(text) < TEXT_MIN_LEN or len(text) > TEXT_MAX_LEN:
        return None

    return _encode_clean(text)


# --------------------------------------------------------------------------- #
# Telegram chat model builder                                                 #
# --------------------------------------------------------------------------- #

def build_tg_chat(chat: Union[ChatGetter, User, Chat, Channel], **kwargs) -> TgChat:
    """
    Build a TgChat model from a Telethon chat object (User, Chat, or Channel).

    Name resolution priority:
        1) chat.title
        2) chat.full_name (Users)
        3) f\"{first_name} {last_name}\" (Users)
        4) empty string fallback

    Chat type resolution:
        - User      -> \"private\"
        - Chat      -> \"group\"
        - Channel   -> \"supergroup\" if megagroup else \"channel\"
        - otherwise -> \"unknown\"
    """
    # Basic attributes (not all are present on all types; getattr is safe).
    username = getattr(chat, "username", None)

    title = getattr(chat, "title", None)
    full_name = getattr(chat, "full_name", None)  # Telethon User convenience
    first_name = getattr(chat, "first_name", "") or ""
    last_name = getattr(chat, "last_name", "") or ""

    # Compose name fallback
    name = title or full_name or f"{first_name} {last_name}".strip()

    # Determine chat type without changing original behavior
    if isinstance(chat, User):
        chat_type = TgChatType.PRIVATE
    elif isinstance(chat, Chat):
        chat_type = TgChatType.GROUP
    elif isinstance(chat, Channel):
        chat_type = TgChatType.SUPER_GROUP if getattr(chat, "megagroup", False) else TgChatType.CHANNEL
    else:
        chat_type = TgChatType.UNKNOWN

    chat_id: int = kwargs.get("chat_id", get_peer_id(chat))

    tg_chat = TgChat(
        id=chat_id,
        username=_encode_clean(username or ""),
        title=_encode_clean(name or ""),
        chat_type=chat_type
    )

    # Log with model id context for observability
    try:
        logger.debug(
            "Built TgChat model",
            extra={"tg_chat_id": chat_id},
        )
    except Exception:
        # Logging must never break functionality
        pass

    return tg_chat


# --------------------------------------------------------------------------- #
# Symbols aggregation                                                         #
# --------------------------------------------------------------------------- #

def _split_csv(csv_value: Optional[str]) -> List[str]:
    """
    Robustly split a comma-separated string into trimmed non-empty tokens.
    """
    if not csv_value:
        return []
    return [part.strip() for part in csv_value.split(",") if part and part.strip()]


def get_symbol_map(copy_setups: List[CopySetup]) -> Dict[str, Set[str]]:
    """
    Collect all allowed symbol names and synonyms from given copy setups.

    Accumulates in the following order:

    1) Base names from cfg_data.SYMBOL_NAMES (each starts with itself as a synonym)
    2) Global synonyms from cfg_data.SYMBOL_SYNONYMS
    3) Per-setup allowed symbols from CopySetup.config.allowed_symbols (CSV unless 'ALL')
    4) Per-setup synonyms from CopySetup.config.symbol_synonyms_mapping

    Returns:
        Ordered mapping: {symbol_name: {synonym1, synonym2, ...}}

    Notes:
        - Preserves insertion order of *keys* (symbols) using OrderedDict.
        - Synonyms are stored in a set (deduplicated; intrinsic order not guaranteed).
        - Intentionally keeps casing as provided (no forced normalization).
    """
    # Start with base symbol names and synonyms from constants
    symbol_map: Dict[str, Set[str]] = OrderedDict((sym_name, {sym_name}) for sym_name in SYMBOL_NAMES)

    # Add global synonyms
    for sym, syns in SYMBOL_SYNONYMS.items():
        # Ensure key exists, then add synonyms
        symbol_map.setdefault(sym, set()).update(set(syns or []))

    # Add from each CopySetup's config (be defensive about config shape)
    for cs in copy_setups or []:
        cfg = getattr(cs, "config", None)
        cs_id = getattr(cs, "id", None)  # for contextual logging

        if cfg is None:
            logger.debug(
                "CopySetup has no config; skipping",
                extra={"model_name_id": cs_id},
            )
            continue

        # Allowed symbols: CSV string unless 'ALL'
        allowed_symbols = getattr(cfg, "allowed_symbols", None)
        if isinstance(allowed_symbols, str) and allowed_symbols.upper() != "ALL":
            for s in _split_csv(allowed_symbols):
                symbol_map.setdefault(s, set()).add(s)

        # Per-setup synonyms mapping (expecting Dict[str, Iterable[str]])
        per_setup_syns = getattr(cfg, "symbol_synonyms_mapping", None)
        if isinstance(per_setup_syns, dict):
            for sym, syns in per_setup_syns.items():
                if not sym:
                    continue
                # Accept list/tuple/set; ignore non-iterables gracefully
                try:
                    symbol_map.setdefault(sym, set()).update(set(syns or []))
                except TypeError:
                    # If a single string accidentally provided, add it as synonym
                    if isinstance(syns, str) and syns.strip():
                        symbol_map.setdefault(sym, set()).add(syns.strip())

        # Per-setup logging (non-blocking)
        try:
            logger.debug(
                "Aggregated symbols from CopySetup",
                extra={"model_name_id": cs_id},
            )
        except Exception:
            pass

    return symbol_map


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #

__all__ = [
    "_encode_clean",
    "filter_message_text",
    "build_tg_chat",
    "get_symbol_map",
]
