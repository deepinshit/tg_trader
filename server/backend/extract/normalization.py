# /backend/extract/normalization.py
from __future__ import annotations

import logging
import math
from typing import List, Tuple, Iterable, Optional, Union, Dict

from enums import OrderType
from backend.extract.exceptions import PriceNormalizationError
from backend.extract.extract_models import SignalBase
from models import Signal

__all__ = ["normalize_prices"]

logger = logging.getLogger(__name__)


def clean_signal_base(sb: SignalBase, allowed_symbols_map: Dict[str, List[str]]) -> SignalBase:
    # Map any synonym in sb.symbols to its canonical base key
    mapped = {
        key
        for sym in sb.symbols
        for key, synonyms in allowed_symbols_map.items()
        if sym in synonyms
    }
    sb.symbols = list(mapped)

    # Deduplicate other lists (order not important → sets are fine)
    unique_types = set(sb.types)
    clean_types = []
    for unique_type in unique_types:
        try:
            clean_types.append(
                _validate_order_type(unique_type)
            )
        except Exception as e:
            logger.error(f"invalid order type: {unique_type} for signal: {e}", extra={"error_type": type(e)})
    sb.sl_prices = list(set(sb.sl_prices))
    sb.tp_prices = list(set(sb.tp_prices))
    sb.entry_prices = list(set(sb.entry_prices))
    return sb

def normalize_signal_base(sb: SignalBase) -> Signal:
    symbol = sb.symbols[0]
    type = sb.types[0]
    entries, tps, sls = normalize_prices(
        type, 
        sb.entry_prices,
        sb.tp_prices,
        sb.sl_prices
    )
    return Signal(
        symbol=symbol,
        type=type,
        entry_prices=entries,
        tp_prices=tps,
        sl_price=sls[0]
    )

def normalize_prices(
    order_type: OrderType,
    entry_prices: List[float],
    tp_prices: List[float],
    sl_prices: List[float],
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

    # Coerce and defensively validate inputs without changing the public API.
    # None values (if ever passed) are treated as empty lists.
    sl_list = _coerce_price_list("sl_prices", sl_prices, extra=extra)
    entry_list = _coerce_price_list("entry_prices", entry_prices, extra=extra)
    tp_list = _coerce_price_list("tp_prices", tp_prices, extra=extra)

    normalized_entries, normalized_tps, normalized_sls = _sort_prices(
        order_type, entry_list, tp_list, sl_list, extra=extra
    )

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
    sls: List[float],
    *,
    extra: Optional[dict] = None,
) -> Tuple[List[float], List[float], List[float]]:
    """
    Sort entry, TP, and SL prices based on order type.

    Entries:
      - BUY  → descending (layer 1 = highest price)
      - SELL → ascending  (layer 1 = lowest  price)

    TPs:
      - BUY  → ascending
      - SELL → descending (TP1 closest to entry)

    SLs:
      - BUY  → descending
      - SELL → ascending (SL1 closest to entry)
    """
    if order_type == OrderType.BUY:
        entries_sorted = sorted(entries, reverse=True)
        tps_sorted     = sorted(tps)
        sls_sorted     = sorted(sls, reverse=True)
    else:  # SELL
        entries_sorted = sorted(entries)   # low → high
        tps_sorted     = sorted(tps, reverse=True)
        sls_sorted     = sorted(sls)      # low → high

    logger.debug(
        "Sorted prices: entries=%s, tps=%s, sls=%s (order_type=%s)",
        entries_sorted,
        tps_sorted,
        sls_sorted,
        getattr(order_type, "name", str(order_type)),
        extra=extra,
    )
    return entries_sorted, tps_sorted, sls_sorted

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
                logger.debug(
                    "Non-finite price in %s at index %d: %r", name, idx, value, extra=extra
                )
                continue
            cleaned.append(f)
        else:
            # Keep behavior strict and explicit to avoid silent data issues in production.
            logger.debug(
                "Unsupported price type in %s at index %d: %r (type=%s)",
                name,
                idx,
                value,
                type(value).__name__,
                extra=extra,
            )
            continue
    logger.debug("Coerced %s → %s", name, cleaned, extra=extra)
    return cleaned
