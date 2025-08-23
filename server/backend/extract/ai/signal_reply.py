# /backend/extract/ai/signal_reply.py
"""
AI-assisted extraction for Signal reply actions.

This module provides a thin, production-ready wrapper around the
LLM helper to obtain a structured `SignalReplyBase` from a free-text
reply and its original `Signal`. The logic and architecture are kept
intentionally minimal (no behavioral changes), while improving:
- input safety (basic validation & truncation)
- observability (clear, structured logging with `extra={'model_name_id': ...}`)
- maintainability (docstrings, type hints, small helpers)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any

from server.backend.extract.ai.openai_helper import _get_structured_output_from_ai
from models import Signal
from backend.extract.ai.prompts import EXTRACT_signal_reply_action_PROMPT
from backend.extract.extract_models import SignalReplyBase

logger = logging.getLogger(__name__)

# --- Tunables (kept conservative to avoid any behavior change) ---
# Prevent runaway prompts on extremely large inputs/objects while still
# keeping meaningful context. Adjust if your model/token budget allows.
_MAX_SERIALIZED_LEN = 4_000  # characters
_MAX_REPLY_TEXT_LEN = 4_000  # characters

# Public API of this module.
__all__ = ["extract_signal_reply_action_ai"]


def _get_model_id(obj: Any) -> Optional[str]:
    """
    Best-effort extraction of a model identifier for logging.

    Respects the requirement to always use logging `extra` with a `model_name_id`
    carrying the related DB model id.
    """
    for attr in ("id", "pk", "uuid", "uid"):
        if hasattr(obj, attr):
            try:
                val = getattr(obj, attr)
                return str(val)
            except Exception:  # pragma: no cover - defensive
                return None
    return None


def _truncate(value: str, limit: int) -> str:
    """Truncate a string to `limit` characters with a clear ellipsis marker."""
    if value is None:
        return ""
    if len(value) <= limit:
        return value
    # Keep head and tail to preserve some context from both ends.
    head = value[: limit // 2]
    tail = value[-(limit // 2 - 3) :]
    return f"{head}...{tail}"


def _safe_serialize_original_signal(original_signal: Signal) -> str:
    """
    Serialize `original_signal` safely for inclusion in the prompt.

    Tries common serialization hooks if available, otherwise falls back
    to `str(obj)`. Result is truncated to avoid token bloat.
    """
    # Prefer explicit serializers if your ORM/model provides them.
    for attr in ("to_dict", "dict", "model_dump", "to_json", "json"):
        if hasattr(original_signal, attr):
            try:
                serializer = getattr(original_signal, attr)
                serialized = serializer()  # type: ignore[operator]
                # If the serializer returns a dict, make it compact but readable.
                if isinstance(serialized, (dict, list)):
                    # Basic compact repr without importing json for simplicity/stability.
                    serialized_str = repr(serialized)
                else:
                    serialized_str = str(serialized)
                return _truncate(serialized_str, _MAX_SERIALIZED_LEN)
            except Exception:  # pragma: no cover - defensive
                break  # fall back to str below

    # Fallback to the object's string representation.
    try:
        return _truncate(str(original_signal), _MAX_SERIALIZED_LEN)
    except Exception:  # pragma: no cover - defensive
        return "<unserializable original_signal>"


async def extract_signal_reply_action_ai(
    text: str,
    original_signal: Signal,
) -> Optional[SignalReplyBase]:
    """
    Get a structured `SignalReplyBase` for a reply `text` in the context of an `original_signal`.

    This function:
      1) Builds a minimal, explicit prompt (system + user) without altering architecture.
      2) Delegates to `_get_structured_output_from_ai` for typed parsing.
      3) Adds robust logging with `extra={'model_name_id': <Signal.id>}`.

    Args:
        text: The raw reply text to analyze.
        original_signal: The original `Signal` instance being replied to.

    Returns:
        A `SignalReplyBase` instance on success; `None` on failure or invalid inputs.
    """
    model_id = _get_model_id(original_signal)
    log_extra = {"model_name_id": model_id}

    if not isinstance(text, str) or not text.strip():
        logger.warning(
            "extract_signal_reply_action_ai: empty or invalid `text` provided; returning None.",
            extra=log_extra,
        )
        return None

    if original_signal is None:
        logger.warning(
            "extract_signal_reply_action_ai: `original_signal` is None; returning None.",
            extra=log_extra,
        )
        return None

    try:
        # Prepare prompt messages (keep roles and structure as in original code).
        serialized_signal = _safe_serialize_original_signal(original_signal)
        trimmed_text = _truncate(text, _MAX_REPLY_TEXT_LEN)

        prompt_list: List[Dict[str, str]] = [
            {"role": "system", "content": f"{EXTRACT_signal_reply_action_PROMPT}"},
            {"role": "system", "content": f"original signal: {serialized_signal}"},
            {"role": "user", "content": f"reply text: {trimmed_text}"},
        ]

        logger.debug(
            "extract_signal_reply_action_ai: prompt constructed; dispatching to AI helper.",
            extra=log_extra,
        )

        result = await _get_structured_output_from_ai(prompt_list, SignalReplyBase)

        if result is None:
            logger.info(
                "extract_signal_reply_action_ai: AI returned no structured result.",
                extra=log_extra,
            )
        else:
            logger.debug(
                "extract_signal_reply_action_ai: structured result received.",
                extra=log_extra,
            )

        return result

    except Exception as exc:
        # Defensive catch-all to avoid bubbling errors into calling layers.
        logger.exception(
            "extract_signal_reply_action_ai: unexpected error while extracting reply action: %s",
            exc,
            extra=log_extra,
        )
        return None
