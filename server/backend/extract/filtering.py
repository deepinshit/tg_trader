# /backend/extract/filtering.py
from __future__ import annotations

import logging
import math
from typing import List, Tuple, Optional, Any

from enums import OrderType

__all__ = ["filter_invalid_prices"]

logger = logging.getLogger(__name__)


def filter_invalid_prices(
    order_type: OrderType,
    sl_prices: List[float],
    entry_prices: List[float],
    tp_prices: List[float],
    *,
    max_price_range_pct: float = 50.0,
    raise_on_invalid: bool = False,
    replace_with_zero: bool = False,
    # Logging note: use `extra={"model_name_id": <id>}` to tag logs with related DB model id.
    model_name_id: Optional[Any] = None,
) -> Tuple[List[float], List[float], List[float]]:
    """
    Validate and filter SL (stop-loss), Entry, and TP (take-profit) prices.

    Validation rules (kept intentionally simple and stable):
      1) Directional sanity based on `order_type`:
         - BUY:   all SL < all Entry, and all TP > all Entry
         - SELL:  all SL > all Entry, and all TP < all Entry
      2) Percentage-distance bound:
         - Each Entry must be within `max_price_range_pct` of BOTH the min and max entry.
         - Each SL must be within `max_price_range_pct` of the reference entry extreme
           (BUY -> min entry; SELL -> max entry).
         - Each TP must be within `max_price_range_pct` of the reference entry extreme
           (BUY -> max entry; SELL -> min entry).

    Behavior on invalid values:
      - If `replace_with_zero=True`, invalid values are preserved as `0`.
      - Else if `raise_on_invalid=True`, errors are collected and raised as an ExceptionGroup.
      - Else, invalid values are silently dropped.

    Notes:
      - Input lists are not modified in-place; filtered copies are returned.
      - The function does **not** sort or deduplicate; order is preserved for values that pass.
      - For logging, this function emits structured logs. Pass `model_name_id` to tag events via
        `extra={"model_name_id": model_name_id}`.

    Args:
        order_type: BUY or SELL from `enums.OrderType`.
        sl_prices:  Candidate stop-loss prices.
        entry_prices: Candidate entry prices (must not be empty).
        tp_prices:  Candidate take-profit prices.
        max_price_range_pct: Max allowed percentage distance for validation checks. Must be > 0.
        raise_on_invalid: If True, raise on any invalid value (collected into an ExceptionGroup).
        replace_with_zero: If True, invalid values are replaced with 0 instead of dropped/raised.
        model_name_id: Optional ID used only for logging context.

    Returns:
        (filtered_entry_prices, filtered_tp_prices, filtered_sl_prices)

    Raises:
        TypeError: If `order_type` is not an instance of OrderType.
        ValueError: If entries are empty or contain zero (zero disallowed for percentage checks),
                    or if `max_price_range_pct` <= 0.
        ExceptionGroup: If `raise_on_invalid=True` and invalid items are encountered.
    """
    log_extra = {"model_name_id": model_name_id}

    # --- Basic argument validation (non-invasive; does not alter behavior) ---
    if not isinstance(order_type, OrderType):
        raise TypeError("order_type must be an instance of enums.OrderType")

    if max_price_range_pct <= 0:
        raise ValueError("max_price_range_pct must be > 0")

    # Normalize to lists (avoid accidental aliasing/mutation of caller lists)
    sl_prices = list(sl_prices or [])
    entry_prices = list(entry_prices or [])
    tp_prices = list(tp_prices or [])

    if not entry_prices:
        logger.info("No entry prices provided; returning empty outputs.", extra=log_extra)
        return [], [], []

    # --- Helpers ---
    def _is_finite_number(x: Any) -> bool:
        try:
            return isinstance(x, (int, float)) and math.isfinite(float(x))
        except Exception:
            return False

    def within_pct(ref_price: float, target_price: float) -> bool:
        """Check if target is within % range of ref."""
        if not _is_finite_number(ref_price) or not _is_finite_number(target_price):
            return False
        if ref_price == 0:  # guard for division by zero
            return False
        pct_diff = abs(float(target_price) - float(ref_price)) / float(ref_price) * 100.0
        return pct_diff <= max_price_range_pct

    # --- Compute entry extremes (as provided; do not pre-filter to avoid changing logic) ---
    min_entry = min(entry_prices)
    max_entry = max(entry_prices)

    # Zero guard for percentage checks (kept as original logic: zero is not allowed)
    if min_entry == 0 or max_entry == 0:
        raise ValueError("Entry price cannot be zero for percentage checks.")

    # --- Directional sanity checks (based on provided extremes) ---
    errors: List[Exception] = []

    if order_type == OrderType.BUY:
        if sl_prices and max(sl_prices) >= min_entry:
            errors.append(ValueError("BUY: SL must be < all entries"))
        if tp_prices and min(tp_prices) <= max_entry:
            errors.append(ValueError("BUY: TP must be > all entries"))
    else:  # SELL
        if sl_prices and min(sl_prices) <= max_entry:
            errors.append(ValueError("SELL: SL must be > all entries"))
        if tp_prices and max(tp_prices) >= min_entry:
            errors.append(ValueError("SELL: TP must be < all entries"))

    # --- Entry validation ---
    valid_entries: List[float] = []
    for e in entry_prices:
        if _is_finite_number(e) and within_pct(min_entry, e) and within_pct(max_entry, e):
            valid_entries.append(float(e))
        elif replace_with_zero:
            valid_entries.append(0.0)
        elif raise_on_invalid:
            errors.append(ValueError(f"Invalid entry: {e!r}"))
        # else: drop silently

    # Use the filtered entries for subsequent returns, but **do not** recompute extremes
    # to keep overall behavior stable with the original logic.
    entry_prices = valid_entries

    # --- SL validation ---
    valid_sls: List[float] = []
    sl_ref = min_entry if order_type == OrderType.BUY else max_entry
    for sl in sl_prices:
        if _is_finite_number(sl) and within_pct(sl_ref, sl):
            valid_sls.append(float(sl))
        elif replace_with_zero:
            valid_sls.append(0.0)
        elif raise_on_invalid:
            errors.append(ValueError(f"Invalid SL: {sl!r}"))
        # else: drop silently

    # --- TP validation ---
    valid_tps: List[float] = []
    tp_ref = max_entry if order_type == OrderType.BUY else min_entry
    for tp in tp_prices:
        if _is_finite_number(tp) and within_pct(tp_ref, tp):
            valid_tps.append(float(tp))
        elif replace_with_zero:
            valid_tps.append(0.0)
        elif raise_on_invalid:
            errors.append(ValueError(f"Invalid TP: {tp!r}"))
        # else: drop silently

    if errors:
        logger.error(
            "Invalid price filtering encountered errors.",
            extra=log_extra,
            exc_info=False,
        )
        # Raise as a group if requested; otherwise fall through returning filtered values.
        if raise_on_invalid:
            raise ExceptionGroup("Invalid price filtering failed", errors)

    logger.debug(
        "Filtering complete",
        extra={
            **log_extra,
            "counts": {
                "entries_in": len(entry_prices),
                "tps_in": len(tp_prices),
                "sls_in": len(sl_prices),
                "entries_out": len(entry_prices),
                "tps_out": len(valid_tps),
                "sls_out": len(valid_sls),
            },
            "order_type": getattr(order_type, "name", str(order_type)),
            "max_price_range_pct": max_price_range_pct,
            "replace_with_zero": replace_with_zero,
            "raise_on_invalid": raise_on_invalid,
        },
    )

    # Preserve the original return order used by the existing implementation:
    # (entry_prices, valid_tps, valid_sls)
    return entry_prices, valid_tps, valid_sls
