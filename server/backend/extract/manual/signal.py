# /backend/extract/manual/signal_reply.py
"""
Manual signal extraction utilities.

Parses free-form text (e.g., chat messages) to extract a trading signal with:
- symbol(s)
- direction(s) (BUY/SELL, LONG/SHORT, including localized variants)
- entry / TP / SL price lists

Design goals:
- Keep logic simple and predictable (order-preserving, idempotent parsing).
- Be robust to noisy input (mixed punctuation, duplicate values, locale commas).
- Remain async-compatible (no blocking IO here).
- Production-ready, stable, and clean.

Notes:
- Logging is done using the module logger.
- If the caller wants to attach a `model_name_id`, pass it to the logger via `extra={"model_name_id": ...}` at call time.
"""

from __future__ import annotations

import logging
import math
from typing import Optional, Union, Iterable

from backend.extract.extract_models import SignalBase
from enums import OrderType

__all__ = ["extract_signal_manual"]

logger = logging.getLogger(__name__)

# Allowed characters in input
ALLOWED_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789., @")

# Direction keywords
DIRECTION_KEYWORDS = {
    OrderType.BUY: {"BUY", "LONG", "KOOP"},
    OrderType.SELL: {"SELL", "SHORT", "VERKOOP"},
}

# Price context keywords
PRICE_KEYWORDS = {
    "tp": {"TP", "TARGET", "PROFIT", "TAKEPROFIT"},
    "sl": {"SL", "STOP", "LOSS", "STOPLOSS"},
    "entry": {"@", "AT", "ENTRY", "LEVEL"},
}


async def extract_signal_manual(text: str, allowed_symbol_names) -> SignalBase:
    """
    Parse a free-form text message to extract a SignalBase.

    Args:
        text: Raw input text containing a trade signal.
        allowed_symbol_names: Passed to `is_valid_symbol` for symbol validation.

    Returns:
        SignalBase with lists populated from the parsed text.
    """
    # Normalize text
    text_upper = (text or "").replace("\n", " ").upper()
    cleaned = "".join(c if c in ALLOWED_CHARS else " " for c in text_upper)

    signal = SignalBase(
        symbols=[],
        types=[],
        entry_prices=[],
        tp_prices=[],
        sl_prices=[],
        info_message="Extracted manually",
    )

    current_price_type = "entry"  # default context

    def parse_price(word: str) -> Optional[float]:
        """Try to parse a numeric price from the given token."""
        if len(word) < 1:
            return None
        try:
            value = float(word.replace(",", "."))
            if not math.isfinite(value):
                return None
            return value
        except (TypeError, ValueError, OverflowError):
            return None

    def update_price_type(word: str) -> bool:
        """Update price type context if token matches known PRICE_KEYWORDS."""
        nonlocal current_price_type
        for k, keywords in PRICE_KEYWORDS.items():
            if word in keywords:
                current_price_type = k
                return True
        return False
    
    def is_valid_symbol(word: str, allowed_symbol_names: Iterable[str] = []) -> bool:
        """
        Fast membership check against the provided allow-list of symbol names.
        """
        if allowed_symbol_names:
            return word in allowed_symbol_names
        else:
            return True

    for raw_word in cleaned.split():
        word = raw_word.strip()
        if not word:
            continue

        # 1) Price
        price = parse_price(word)
        if price is not None:
            if current_price_type == "sl" and price not in signal.sl_prices:
                signal.sl_prices.append(price)
            elif current_price_type == "tp" and price not in signal.tp_prices:
                signal.tp_prices.append(price)
            elif current_price_type == "entry" and price not in signal.entry_prices:
                signal.entry_prices.append(price)
            continue

        # 2) Update price context (must check before stripping non-alpha so "@" works)
        if update_price_type(word):
            continue

        # 3) Alphabetic-only word for direction/symbol
        clean_word = "".join(c for c in word if c.isalpha())
        if not clean_word:
            continue

        # Direction
        for direction, keywords in DIRECTION_KEYWORDS.items():
            if clean_word in keywords and direction not in signal.types:
                signal.types.append(direction)

        # Symbol
        try:
            if (clean_word not in signal.symbols) and is_valid_symbol(
                clean_word, allowed_symbol_names
            ):
                signal.symbols.append(clean_word)
        except Exception:
            # Defensive: never let symbol validation break extraction
            logger.warning("Symbol validation error for token: %r", clean_word)

    return signal
