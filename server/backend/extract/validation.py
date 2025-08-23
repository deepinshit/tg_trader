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

from typing import Iterable, List, Optional
import logging
import math

from enums import OrderType
from backend.extract.extract_models import SignalBase
from backend.extract.exceptions import SignalValidationError

__all__ = [
    "validate_prices",
    "validate_signal_base",
    "is_valid_symbol",
]

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Price validations
# --------------------------------------------------------------------------- #
def validate_prices(
    order_type: OrderType,
    sl_prices: List[float],
    entry_prices: List[float],
    tp_prices: List[float],
    *,
    max_entry_prices: int = -1,
    min_entry_prices: int = 1,
    max_tp_prices: int = -1,
    min_tp_prices: int = 1,
    max_sl_prices: int = 1,
    min_sl_prices: int = 1,
    model_name_id: Optional[int] = None,
) -> None:
    """
    Validate the normalized price lists for expected counts and logical consistency.

    Parameters
    ----------
    order_type : OrderType
        BUY or SELL.
    sl_prices : List[float]
        Stop-loss prices (normalized & filtered).
    entry_prices : List[float]
        Entry prices (normalized & filtered).
    tp_prices : List[float]
        Take-profit prices (normalized & filtered).
    max_entry_prices, min_entry_prices, max_tp_prices, min_tp_prices,
    max_sl_prices, min_sl_prices : int
        Expected range constraints for the price list lengths.
        Use -1 for "no upper bound" on the corresponding *max_* parameters.
    model_name_id : Optional[int]
        If provided, used in logs via `extra={'model_name_id': model_name_id}`.

    Raises
    ------
    ExceptionGroup
        Raised with one or more `ValueError` items describing all failed checks.
    """
    extra = {"model_name_id": model_name_id}
    logger.debug(
        "Starting validate_prices",
        extra=extra,
    )

    errors = []

    # Type & numeric sanity checks (finite numbers only)
    def _check_finite(name: str, values: List[float]) -> None:
        nonlocal errors
        for idx, v in enumerate(values):
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                errors.append(ValueError(f"{name}[{idx}] must be a finite number, got {v!r}"))

    _check_finite("entry_prices", entry_prices)
    _check_finite("tp_prices", tp_prices)
    _check_finite("sl_prices", sl_prices)

    # Count validations
    if max_entry_prices != -1 and len(entry_prices) > max_entry_prices:
        errors.append(ValueError(f"Too many entry prices: {len(entry_prices)} > max {max_entry_prices}"))

    if len(entry_prices) < min_entry_prices:
        errors.append(ValueError(f"Too few entry prices: {len(entry_prices)} < min {min_entry_prices}"))

    if max_tp_prices != -1 and len(tp_prices) > max_tp_prices:
        errors.append(ValueError(f"Too many TP prices: {len(tp_prices)} > max {max_tp_prices}"))

    if len(tp_prices) < min_tp_prices:
        errors.append(ValueError(f"Too few TP prices: {len(tp_prices)} < min {min_tp_prices}"))

    if max_sl_prices != -1 and len(sl_prices) > max_sl_prices:
        errors.append(ValueError(f"Too many SL prices: {len(sl_prices)} > max {max_sl_prices}"))

    if len(sl_prices) < min_sl_prices:
        errors.append(ValueError(f"Too few SL prices: {len(sl_prices)} < min {min_sl_prices}"))

    # Logical validations
    if not _is_monotonic(entry_prices, order_type):
        errors.append(ValueError(f"Entry prices are not correctly ordered for {order_type.name}: {entry_prices}"))

    if entry_prices:
        highest_entry = max(entry_prices)
        lowest_entry = min(entry_prices)

        if order_type == OrderType.BUY:
            if tp_prices and min(tp_prices) <= highest_entry:
                errors.append(
                    ValueError(
                        f"TP prices must be strictly above highest entry price {highest_entry}, got {tp_prices}"
                    )
                )
            if sl_prices and max(sl_prices) >= lowest_entry:
                errors.append(
                    ValueError(
                        f"SL prices must be strictly below lowest entry price {lowest_entry}, got {sl_prices}"
                    )
                )
        else:
            if tp_prices and max(tp_prices) >= lowest_entry:
                errors.append(
                    ValueError(
                        f"TP prices must be strictly below lowest entry price {lowest_entry}, got {tp_prices}"
                    )
                )
            if sl_prices and min(sl_prices) <= highest_entry:
                errors.append(
                    ValueError(
                        f"SL prices must be strictly above highest entry price {highest_entry}, got {sl_prices}"
                    )
                )

    if errors:
        # Log once with all messages to keep logs concise & structured.
        logger.warning(
            "Price validation failed with %d error(s): %s",
            len(errors),
            "; ".join(str(e) for e in errors),
            extra=extra,
        )
        raise ExceptionGroup("Price validation errors", errors)

    logger.debug("Price validation passed", extra=extra)


def _is_monotonic(prices: List[float], order_type: OrderType) -> bool:
    """
    Check monotonic order of entries:
      - BUY: descending (each next value <= previous)
      - SELL: ascending (each next value >= previous)

    Empty or single-element lists are considered monotonic.
    """
    if not prices or len(prices) == 1:
        return True

    if order_type == OrderType.BUY:
        return all(earlier >= later for earlier, later in zip(prices, prices[1:]))
    else:
        return all(earlier <= later for earlier, later in zip(prices, prices[1:]))


# --------------------------------------------------------------------------- #
# Misc helpers
# --------------------------------------------------------------------------- #
def is_valid_symbol(word: str, allowed_symbol_names: Iterable[str]) -> bool:
    """
    Fast membership check against the provided allow-list of symbol names.
    """
    return word in allowed_symbol_names


# --------------------------------------------------------------------------- #
# SignalBase validations
# --------------------------------------------------------------------------- #
def validate_signal_base(signal_base: SignalBase, *, model_name_id: Optional[int] = None) -> SignalBase:
    """
    Validate and clean a `SignalBase` instance:
    - Deduplicate list fields while preserving original order.
    - Ensure required fields are present.
    - Enforce singleton for `symbol` and `type`.

    Parameters
    ----------
    signal_base : SignalBase
        Instance to validate. Its `model_dump()` is used for field iteration.
    model_name_id : Optional[int]
        If provided, used in logs via `extra={'model_name_id': model_name_id}`.

    Returns
    -------
    SignalBase
        A new, cleaned, validated instance.

    Raises
    ------
    ExceptionGroup
        With one or more `SignalValidationError` describing all issues.
    """
    extra = {"model_name_id": model_name_id}
    logger.debug("Starting validate_signal_base", extra=extra)

    errors: List[SignalValidationError] = []
    cleaned_data = {}

    # Iterate over dumped payload to avoid mutating the original model.
    for key, value in signal_base.model_dump().items():
        # Pass-through fields that are not list-like or should not be touched.
        if key == "info_message":
            cleaned_data[key] = value
            continue

        # Defensive: treat non-list values as a single-item list (without changing behavior
        # for well-formed inputs). This keeps the logic robust without altering architecture.
        values_list = value if isinstance(value, list) else [value]

        # Deduplicate while preserving order
        seen = set()
        new_value = [x for x in values_list if not (x in seen or seen.add(x))]

        if not new_value:
            errors.append(SignalValidationError(key, "Missing value"))

        # Check singleton fields
        if key in {"symbol", "type"}:
            if len(new_value) != 1:
                errors.append(SignalValidationError(key, "Multiple values not allowed"))

        cleaned_data[key] = new_value

    if errors:
        logger.warning(
            "SignalBase validation failed with %d error(s): %s",
            len(errors),
            "; ".join(f"{e.field}: {e.message}" for e in errors),
            extra=extra,
        )
        raise ExceptionGroup("SignalBase validation failed", list(errors))

    validated = SignalBase(**cleaned_data)
    logger.debug("SignalBase validation passed", extra=extra)
    return validated
