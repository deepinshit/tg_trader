# /backend/extract/manual/signal_reply.py

from __future__ import annotations

import logging
import re
from typing import Iterable, List, Optional, Pattern, Tuple, Union

from enums import SignalReplyAction

__all__ = ["extract_signal_reply_action_manual"]

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Keyword configuration (kept simple and close to original to avoid logic/arch changes)
# --------------------------------------------------------------------------------------

# NOTE: Keep these sets concise to avoid unintended matches. Multi-word phrases are
# checked verbatim (with flexible whitespace). Single words will match basic inflections
# (e.g., exit/exits/exiting; close/closed/closing).
CLOSE_KEYWORDS: Tuple[str, ...] = (
    "CLOSE",
    "EXIT",
    "TERMINATE",
    "CLOSING POSITION",
    "CANCEL",
    "CLOSING",
)

BREAKEVEN_KEYWORDS: Tuple[str, ...] = (
    "SET BE",
    "LOCK IN",
    "PROFIT",
    "BREAKEVEN",
    "MOVE SL",
    "SL TO ENTRY",
)


def _compile_patterns(keywords: Iterable[str]) -> List[Tuple[Pattern[str], str]]:
    """
    Compile robust regex patterns for each keyword.

    - For multi-word phrases, we require token word boundaries and flexible whitespace.
    - For single words, we match the word plus common suffixes (\\w*), while ensuring
      a leading word boundary to avoid partials like 'enclose' matching 'close'.
    """
    compiled: List[Tuple[Pattern[str], str]] = []
    for kw in keywords:
        if " " in kw:
            # Multi-word phrase: \bWORD\s+WORD(\s+WORD)?\b with case-insensitive match.
            tokens = [re.escape(tok) for tok in kw.split()]
            pattern_str = r"\b" + r"\s+".join(tokens) + r"\b"
        else:
            # Single word: \bWORD\w*\b to allow simple inflections (close/closed/closing, exit/exits/exiting).
            pattern_str = r"\b" + re.escape(kw) + r"\w*\b"

        compiled.append((re.compile(pattern_str, flags=re.IGNORECASE), kw))
    return compiled


# Pre-compile patterns once at import for performance and consistency.
_CLOSE_PATTERNS: List[Tuple[Pattern[str], str]] = _compile_patterns(CLOSE_KEYWORDS)
_BREAKEVEN_PATTERNS: List[Tuple[Pattern[str], str]] = _compile_patterns(BREAKEVEN_KEYWORDS)


def _contains_any(text: str, patterns: List[Tuple[Pattern[str], str]]) -> Optional[str]:
    """
    Return the original keyword that matches `text`, or None if no pattern matches.
    """
    for pattern, original_kw in patterns:
        if pattern.search(text):
            return original_kw
    return None


def extract_signal_reply_action_manual(
    text: str,
    *,
    model_name_id: Optional[Union[int, str]] = None,
) -> Optional[SignalReplyAction]:
    """
    Parses a free-form reply message and returns a corresponding SignalReplyAction
    if a known keyword is detected.

    Priority:
        - CLOSE has higher priority than BREAKEVEN if both categories appear.

    Parameters
    ----------
    text : str
        Free-form reply message.
    model_name_id : Optional[Union[int, str]], keyword-only
        Optional database model identifier used for structured logging. When provided,
        it is attached to logs via `extra={'model_name_id': model_name_id}`.

    Returns
    -------
    Optional[SignalReplyAction]
        SignalReplyAction.CLOSE or SignalReplyAction.BREAKEVEN if matched; otherwise None.

    Notes
    -----
    - Matching is case-insensitive.
    - Newlines and excessive internal whitespace are normalized.
    - Single-word keywords match simple suffix variations (e.g., "exit", "exiting").
    - Multi-word phrases require the words in order, allowing flexible whitespace.
    """
    extra = {"model_name_id": model_name_id} if model_name_id is not None else None

    try:
        if not isinstance(text, str):
            logger.debug(
                "extract_signal_reply_action_manual: non-string input -> returning None",
                extra=extra,
            )
            return None

        # Normalize whitespace and trim. Keep content otherwise intact for regex matching.
        normalized_text = " ".join(text.replace("\n", " ").split())
        if not normalized_text:
            logger.debug(
                "extract_signal_reply_action_manual: empty/whitespace input -> None",
                extra=extra,
            )
            return None

        # Check for actions (CLOSE has higher priority if both are present).
        close_kw = _contains_any(normalized_text, _CLOSE_PATTERNS)
        if close_kw is not None:
            logger.debug(
                "extract_signal_reply_action_manual: matched CLOSE keyword '%s'",
                close_kw,
                extra=extra,
            )
            return SignalReplyAction.CLOSE

        be_kw = _contains_any(normalized_text, _BREAKEVEN_PATTERNS)
        if be_kw is not None:
            logger.debug(
                "extract_signal_reply_action_manual: matched BREAKEVEN keyword '%s'",
                be_kw,
                extra=extra,
            )
            return SignalReplyAction.BREAKEVEN

        logger.debug(
            "extract_signal_reply_action_manual: no keyword matched -> None",
            extra=extra,
        )
        return None

    except Exception as exc:  # Defensive: never propagate unexpected parsing errors.
        logger.exception(
            "extract_signal_reply_action_manual: unexpected error: %s", exc, extra=extra
        )
        return None


# --------------------------------------------------------------------------------------
# Minimal self-check (manual) — safe to leave; does not affect library usage
# --------------------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.DEBUG)
    samples = [
        "Please CLOSE the trade.",
        "we are exiting now",
        "lock in profit and move SL to entry",
        "set be pls",
        "No action.",
        "Consider canceling this position",
        "We will breakeven soon",
        "The enclosure is damaged (should NOT trigger CLOSE).",
    ]
    for s in samples:
        print(s, "->", extract_signal_reply_action_manual(s, model_name_id="demo-1"))
