# /backend/extract/functions.py
"""
High-level extraction helpers for trading signals and signal replies.

This module orchestrates the following workflow for extracting a Signal from a
Message:
    1) Manual extraction of raw fields (symbols, prices, order type).
    2) Normalization (deduplicate & map synonyms to canonical base symbol keys).
    3) Validation of required fields.
    4) If the number of validation errors is below a configured threshold,
       attempt AI extraction as a fallback.
    5) Final price normalization, filtering, and validation.
    6) Return a fully-validated Signal or None.

Design notes (no behavior changes vs. original):
- Logic/architecture is preserved. Improvements focus on resilience,
  clarity, and production-grade logging/docstrings.
- Logging uses `extra={"model_name_id": <Message.id>}` to tag records with the
  related DB model id, per project convention.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set

from backend.extract.ai.signal import extract_signal_ai
from backend.extract.manual.signal import extract_signal_manual
from backend.extract.manual.signal_reply import extract_signal_reply_action_manual
from backend.extract.normalization import clean_signal_base, normalize_signal_base
from backend.extract.filtering import filter_invalid_prices
from backend.extract.validation import validate_signal_base
from backend.extract.extract_models import SignalBase, SignalReplyBase  # noqa: F401 (kept for architecture consistency)
from cfg import MAX_EXCEPTIONS_FOR_AI_SIGNAL_EXTRACTION
from enums import OrderType  # noqa: F401 (type retained for downstream compatibility)
from models import Message, Signal, SignalReply

logger = logging.getLogger(__name__)

__all__ = ["get_signal_from_text", "get_signal_reply_action_from_text"]


async def get_signal_from_text(
    message: Message,
    allowed_symbols_map: Dict[str, Set[str]],
) -> Optional[Signal]:
    """
    Extract a trading signal from a message text.

    The function attempts a manual extraction first. If the partially-extracted
    structure is "signal-ish" (i.e., has fewer than
    MAX_EXCEPTIONS_FOR_AI_SIGNAL_EXTRACTION validation errors), an AI fallback
    extraction is attempted. Finally, prices are normalized, filtered, and
    validated before constructing a `Signal`.

    Parameters
    ----------
    message : Message
        The message instance containing the source text. Its `id` is used for
        log correlation via logger `extra={"model_name_id": message.id}`.
    allowed_symbols_map : Dict[str, Set[str]]
        Mapping of canonical base symbols (keys) to a set of acceptable names
        and synonyms (values). Example:
            {
                "XAUUSD": {"XAUUSD", "GOLD", "XAU", "GOLDUSD"},
                "EURUSD": {"EURUSD", "EUR/USD", "EURO", "EUR"},
            }

    Returns
    -------
    Optional[Signal]
        A fully validated `Signal` if extraction succeeds; otherwise, `None`.

    Notes
    -----
    - Exceptions from manual/AI extraction are logged and result in `None`,
      except when AI extraction returns a structure that still fails validation:
      in that case, an ExceptionGroup is raised (unchanged from original logic).





    extract manual
    normalize
        all values unique
        symbol mapped
        prices sorted
    validate
        each field has at least 1 value, only some multiple.
    extract ai
    normalize
    validate

    filtering prices on distribution level
    validating prices on trade level 
    """
    # Prepare structured logging "extra" with the related DB model id
    msg_extra = {"message_id": message.id}

    # Defensive read/early exit on empty text
    text: str = (message.text or "").strip()
    if not text:
        logger.debug("Empty or whitespace-only message text; nothing to extract.", extra=msg_extra)
        return None

    # Flatten all allowed symbols & synonyms for parsing (order not required)
    if not allowed_symbols_map:
        logger.debug("Allowed symbols map is empty; manual extraction may yield no symbols.", extra=msg_extra)
    allowed_symbol_names = list(set().union(*allowed_symbols_map.values())) if allowed_symbols_map else []

    logger.debug("Starting manual signal extraction.", extra=msg_extra)

    # Step 1 — Manual extraction
    signal_base: Optional[SignalBase] = None
    try:
        signal_base = await extract_signal_manual(text, allowed_symbol_names)
    except Exception as e:
        logger.exception(
            "Error during manual signal extraction.",
            extra={**msg_extra, "error_type": type(e).__name__},
        )
        return None

    if signal_base is None: # impossible
        logger.debug("Manual extraction returned None.", extra=msg_extra)
        return None
    
    logger.info(f"manual extracted signal: {signal_base}", extra=msg_extra)

    # Step 2 — Normalize + validate manual extraction
    signal_base = clean_signal_base(signal_base, allowed_symbols_map)
    errors = validate_signal_base(signal_base)
    if errors:
        fallback_to_ai = len(errors) < MAX_EXCEPTIONS_FOR_AI_SIGNAL_EXTRACTION
        # Keep errors in debug; they are expected during coarse manual parse
        logger.info(f"got {len(errors)} (fallback_to_ai={fallback_to_ai}) Manual extraction validation errors: {','.join(str(e) for e in errors)}", extra=msg_extra)

        # Step 3 — Fallback to AI if "signal-ish" but incomplete
        if not fallback_to_ai:
            return None
        else:
            signal_base: Optional[SignalBase] = None
            logger.debug("Attempting AI extraction fallback.", extra=msg_extra)

            try:
                signal_base = await extract_signal_ai(text)
            except Exception as e:
                logger.exception(
                    "Error during AI signal extraction.",
                    extra={**msg_extra, "error_type": type(e).__name__},
                )
                return None

            if signal_base is None:
                logger.debug("AI extraction returned None.", extra=msg_extra)
                return None
            
            logger.info(f"AI extracted signal: {signal_base}", extra=msg_extra)

            # Step 2 — Normalize + validate manual extraction
            signal_base = clean_signal_base(signal_base, allowed_symbols_map)
            errors = validate_signal_base(signal_base)
            if errors:
                # Keep errors in debug; they are expected during coarse manual parse
                logger.info(f"got {len(errors)} AI extraction validation errors: {','.join(str(e) for e in errors)}", extra=msg_extra)
                return None
            
    try:
        normalized_signal: Signal = normalize_signal_base(signal_base)

        # Filter entries & TPs based on SL
        filtered_entries, filtered_tps = filter_invalid_prices(
            order_type=normalized_signal.type,
            sl_price=normalized_signal.sl_price,
            entry_prices=normalized_signal.entry_prices,
            tp_prices=normalized_signal.tp_prices
        )
    except Exception as e:
        logger.exception(
            "Exception while normalizing and filtering SignalBase -> Signal",
            extra={**msg_extra, "error": str(e), "error_type": type(e).__name__},
        )
        return None

    # ✅ Safely create a new instance
    new_signal = normalized_signal.copy(
        entry_prices=filtered_entries,
        tp_prices=filtered_tps
    )

    return new_signal


async def get_signal_reply_action_from_text(
    message: Message,
    reply_to_signal: Signal,
    use_ai: bool = False,
) -> Optional[SignalReply]:
    """
    Extract a signal-reply action (e.g., close/modify) from a reply message.

    Parameters
    ----------
    message : Message
        The reply message whose text will be parsed.
    reply_to_signal : Signal
        The original signal being replied to (reserved for future use if AI
        extraction is introduced; not used in manual extraction path).
    use_ai : bool, default False
        Whether to attempt AI-based extraction. Currently not implemented.

    Returns
    -------
    Optional[SignalReply]
        A `SignalReply` if manual extraction succeeds; otherwise, `None`.
    """
    msg_extra = {"model_name_id": message.id}

    if not use_ai:
        logger.debug("Manual signal reply extraction.", extra=msg_extra)
        # Manual path is synchronous by design; preserve original behavior
        return extract_signal_reply_action_manual(message.text)

    logger.debug("AI signal reply extraction not implemented.", extra=msg_extra)
    return None
