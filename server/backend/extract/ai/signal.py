# /backend/extract/ai/signal.py
"""
Signal extraction via AI.

This module provides a single asynchronous function, `extract_signal_ai`, which sends
a minimal, well-structured prompt to the AI and returns a `SignalBase` instance
parsed by `_get_structured_output_from_ai`.

Design goals:
- Production-ready: input validation, structured logging, defensive error handling.
- Robust yet simple: preserves the original logic/architecture and behavior.
- Professional & documented: clear types, docstrings, and non-invasive safeguards.
- Scalable/Flexible: accepts an optional `model_name_id` for consistent, correlated logging.

IMPORTANT LOGGING NOTE:
- When logging, we use `extra={"model_name_id": <id>}` so upstream handlers can
  enrich records (e.g., JSON logs, correlation IDs).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Union

from backend.extract.ai.openai_helper import _get_structured_output_from_ai
from backend.extract.ai.prompts import EXTRACT_SIGNAL_PROMPT
from backend.extract.extract_models import SignalBase

__all__ = ["extract_signal_ai"]

logger = logging.getLogger(__name__)


async def extract_signal_ai(
    text: str,
    *,
    model_name_id: Optional[Union[int, str]] = None,
) -> Optional[SignalBase]:
    """
    Extract a `SignalBase` object from free-form `text` using the AI.

    Parameters
    ----------
    text : str
        The user/content text to analyze. Must be a non-empty string.
    model_name_id : Optional[Union[int, str]]
        Optional identifier of the related DB model for correlated logging.
        Included in log records via `extra={"model_name_id": ...}`.

    Returns
    -------
    Optional[SignalBase]
        A populated SignalBase instance on success, or `None` if extraction fails
        or yields no result.

    Notes
    -----
    - Does not log the raw input `text` to avoid leaking sensitive content.
    - Preserves the original minimal prompt structure and AI call path.
    - Any exceptions from the underlying AI call are caught, logged, and result
      in a `None` return to keep callers resilient.
    """
    extra_log = {"model_name_id": model_name_id, "component": "extract_signal_ai"}

    # Basic input validation (non-invasive).
    if text is None:
        logger.warning("No text provided to extract_signal_ai (None).", extra=extra_log)
        return None

    text_stripped = text.strip()
    if not text_stripped:
        logger.warning("Empty text provided to extract_signal_ai after stripping.", extra=extra_log)
        return None

    # Construct the prompt exactly as before (no architectural/logic change).
    prompt_list: List[Dict[str, str]] = [
        {"role": "system", "content": f"{EXTRACT_SIGNAL_PROMPT}"},
        {"role": "user", "content": f"reply text: {text_stripped}"},
    ]

    # Avoid logging the complete prompt or user text; keep logs minimal & safe.
    logger.debug(
        "Submitting prompt to AI for signal extraction.",
        extra={**extra_log, "input_len": len(text_stripped)},
    )

    try:
        result = await _get_structured_output_from_ai(prompt_list, SignalBase)
    except Exception as exc:  # Defensive: keep callers safe from lower-level failures.
        logger.exception(
            "Signal extraction via AI failed.",
            extra={**extra_log, "error_class": exc.__class__.__name__},
        )
        return None

    if result is None:
        logger.info("AI returned no structured signal.", extra=extra_log)
        return None

    if not isinstance(result, SignalBase):
        # Defensive sanity check; do not attempt to coerce to avoid changing logic.
        logger.warning(
            "AI returned unexpected type for signal.",
            extra={**extra_log, "returned_type": type(result).__name__},
        )
        return None

    logger.info("Signal extracted successfully.", extra=extra_log)
    return result
