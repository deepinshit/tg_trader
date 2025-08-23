# /backend/extract/normalization.py
from __future__ import annotations

import logging
import math
from typing import List, Tuple, Iterable, Optional, Union

from enums import OrderType
from backend.extract.exceptions import PriceNormalizationError

__all__ = ["normalize_prices"]

logger = logging.getLogger(__name__)


def normalize_prices(
    order_type: OrderType,
    sl_prices: List[float],
    entry_prices: List[float],
    tp_prices: List[float],
    *,
    model_name_id: Optional[Union[int, str]] = None,
) -> Tuple[List[float], List[float], List[float]]:
    """
    Normalize SL, Entry, and TP prices.

    Behavior (unchanged):
      • Entries:
          - BUY  → sort descending (layer 1 = highest price)
          - SELL → sort ascending  (layer 1 = lowest  price)
      • TPs:
          - Always sort ascending, then
          - SELL → reverse to descending
      • SLs:
          - Always sort ascending

    Parameters:
        order_type (OrderType): BUY or SELL.
        sl_prices (List[float]): Stop-loss prices.
        entry_prices (List[float]): Entry prices.
        tp_prices (List[float]): Take-profit prices.
        model_name_id (Optional[Union[int, str]]): If provided, it will be attached to
            log records via `extra={"model_name_id": model_name_id}` as requested.

    Returns:
        Tuple[List[float], List[float], List[float]]:
            (normalized_entry_prices, normalized_tp_prices, normalized_sl_prices)

    Raises:
        PriceNormalizationError: If `order_type` is invalid or prices contain non-finite
            numbers (NaN/inf) or unsupported types.
    """
    extra = {"model_name_id": model_name_id} if model_name_id is not None else None

    _validated_order_type = _validate_order_type(order_type, extra=extra)

    # Coerce and defensively validate inputs without changing the public API.
    # None values (if ever passed) are treated as empty lists.
    sl_list = _coerce_price_list("sl_prices", sl_prices, extra=extra)
    entry_list = _coerce_price_list("entry_prices", entry_prices, extra=extra)
    tp_list = _coerce_price_list("tp_prices", tp_prices, extra=extra)

    normalized_entries, normalized_tps = _sort_prices(
        _validated_order_type, entry_list, tp_list, extra=extra
    )
    normalized_sls = sorted(sl_list)

    logger.debug(
        "Price normalization completed: entries=%s, tps=%s, sls=%s",
        normalized_entries,
        normalized_tps,
        normalized_sls,
        extra=extra,
    )
    return normalized_entries, normalized_tps, normalized_sls


def _sort_prices(
    order_type: OrderType,
    entries: List[float],
    tps: List[float],
    *,
    extra: Optional[dict] = None,
) -> Tuple[List[float], List[float]]:
    """
    Sort entry and TP prices based on order type (logic unchanged).

    Entries:
      - BUY  → descending (layer 1 = highest price)
      - SELL → ascending  (layer 1 = lowest  price)

    TPs:
      - Sort ascending, then reverse for SELL (so that TP1 is closest for SELL).

    Args:
        order_type: The order side (BUY/SELL).
        entries: List of entry prices.
        tps: List of take-profit prices.
        extra: Optional logging `extra` (e.g., {"model_name_id": <id>}).

    Returns:
        (entries_sorted, tps_sorted)
    """
    if not entries:
        entries_sorted: List[float] = []
    else:
        entries_sorted = sorted(entries)
        if order_type == OrderType.BUY:
            entries_sorted = entries_sorted[::-1]

    if not tps:
        tps_sorted: List[float] = []
    else:
        tps_sorted = sorted(tps)
        if order_type == OrderType.SELL:
            tps_sorted = tps_sorted[::-1]

    logger.debug(
        "Sorted prices: entries_sorted=%s, tps_sorted=%s (order_type=%s)",
        entries_sorted,
        tps_sorted,
        getattr(order_type, "name", str(order_type)),
        extra=extra,
    )
    return entries_sorted, tps_sorted


# -------------------------
# Internal helpers (private)
# -------------------------

def _validate_order_type(order_type: OrderType, *, extra: Optional[dict] = None) -> OrderType:
    """
    Validate or coerce the order_type to an OrderType enum. Raises a domain exception on error.
    """
    try:
        if isinstance(order_type, OrderType):
            return order_type
        # Best-effort coercion (supports strings like "BUY"/"SELL" or the enum value)
        return OrderType(order_type)  # may raise ValueError
    except Exception as exc:
        logger.exception("Invalid order_type: %r", order_type, extra=extra)
        raise PriceNormalizationError(f"Invalid order_type: {order_type!r}") from exc


def _coerce_price_list(
    name: str,
    prices: Optional[Iterable[float]],
    *,
    extra: Optional[dict] = None,
) -> List[float]:
    """
    Convert an iterable of numeric prices to a clean list[float].

    - Accepts None → returns [] (defensive, keeps API stable in practice).
    - Ensures each item is int/float and finite (no NaN/inf).
    - Converts ints to floats.
    - Leaves duplicates intact (no behavioral change).
    """
    if prices is None:
        logger.debug("Price list %s is None; treating as empty list.", name, extra=extra)
        return []

    cleaned: List[float] = []
    for idx, value in enumerate(prices):
        if isinstance(value, (int, float)):
            f = float(value)
            if not math.isfinite(f):
                logger.error(
                    "Non-finite price in %s at index %d: %r", name, idx, value, extra=extra
                )
                raise PriceNormalizationError(
                    f"Non-finite price in {name} at index {idx}: {value!r}"
                )
            cleaned.append(f)
        else:
            # Keep behavior strict and explicit to avoid silent data issues in production.
            logger.error(
                "Unsupported price type in %s at index %d: %r (type=%s)",
                name,
                idx,
                value,
                type(value).__name__,
                extra=extra,
            )
            raise PriceNormalizationError(
                f"Unsupported price type in {name} at index {idx}: {value!r}"
            )

    logger.debug("Coerced %s → %s", name, cleaned, extra=extra)
    return cleaned
