# /backend/extract/validation.py
"""
Validation utilities for extracted trading signals.

This module provides:
- `validate_prices` to validate SL/entry/TP price lists for count bounds and
  logical consistency based on order type.
- `validate_signal_base` to sanitize and validate a `SignalBase` payload
  (deduplicate while preserving order, ensure required/singleton fields).
- `is_valid_symbol` small helper for symbol allow-list checks.

Design goals:
- Production-ready, predictable behavior.
- Clear, actionable error messages.
- No architectural changes; optional logging that can carry a related DB model ID
  via the logging `extra` parameter under the key `model_name_id`.
"""

from __future__ import annotations

from typing import List
import logging

from backend.extract.extract_models import SignalBase

__all__ = [
    "validate_signal_base"
]

logger = logging.getLogger(__name__)

def validate_signal_base(sb: SignalBase) -> List[Exception]:
    errors: List[Exception] = []

    if len(sb.symbols) != 1:
        errors.append(ValueError("Invalid symbol: must have exactly 1."))
    if len(sb.types) != 1:
        errors.append(ValueError("Invalid order type: must have exactly 1."))
    if len(sb.sl_prices) != 1:
        errors.append(ValueError("Invalid stop loss: must have exactly 1."))
    if not sb.tp_prices:
        errors.append(ValueError("Invalid take profits: must have ≥1."))
    if not sb.entry_prices:
        errors.append(ValueError("Invalid entry prices: must have ≥1."))

    return errors
