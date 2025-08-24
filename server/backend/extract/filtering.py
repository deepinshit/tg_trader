# /backend/extract/filtering.py
from __future__ import annotations

import logging
from typing import List, Tuple, Optional, Any

from enums import OrderType

__all__ = ["filter_invalid_prices"]

logger = logging.getLogger(__name__)


def filter_invalid_prices(
    order_type: OrderType,
    sl_price: float,
    entry_prices: List[float],
    tp_prices: List[float],
    *,
    max_entries: Optional[int] = None,
    max_tps: Optional[int] = None,
    ignore_invalid: bool = True,
    model_name_id: Optional[Any] = None,
) -> Tuple[List[float], List[float]]:
    """
    Filter entries and TPs based on a single SL price and order type rules.

    Validation Rules:
    - BUY:  sl < min(entry) < max(entry) < min(tp)
    - SELL: sl > max(entry) > min(entry) > max(tp)

    Assumes:
    - Input prices are finite, positive numbers.
    - Entries sorted ascending.
    - TPs sorted by preference.

    Args:
        order_type: BUY or SELL order type.
        sl_price: Single stop loss price.
        entry_prices: Entry price candidates (must not be empty).
        tp_prices: Take profit price candidates.
        max_entries: Maximum number of entry prices to keep.
        max_tps: Maximum number of TP prices to keep.
        ignore_invalid: If True, drop invalid prices; else raise ValueError.
        model_name_id: Optional ID for logging context.

    Returns:
        Tuple of (filtered_entry_prices, filtered_tp_prices).

    Raises:
        ValueError: If no valid entries or TPs remain when ignore_invalid=False.
    """
    log_extra = {"model_name_id": model_name_id}

    if not entry_prices:
        raise ValueError("entry_prices cannot be empty")

    # Filter entries based on SL price
    if order_type == OrderType.BUY:
        valid_entries = [e for e in entry_prices if e > sl_price]
    else:  # SELL
        valid_entries = [e for e in entry_prices if e < sl_price]

    # If no valid entries remain
    if not valid_entries:
        msg = f"No valid entry prices remain for {order_type.name} with SL={sl_price}"
        if ignore_invalid:
            entry_prices = []
        else:
            raise ValueError(msg)
    else:
        entry_prices = valid_entries

    # Filter TPs based on filtered entries
    if entry_prices:
        min_entry = min(entry_prices)
        max_entry = max(entry_prices)
        if order_type == OrderType.BUY:
            valid_tp = [tp for tp in tp_prices if tp > max_entry]
        else:  # SELL
            valid_tp = [tp for tp in tp_prices if tp < min_entry]
    else:
        valid_tp = []

    # Handle invalid TPs
    if not valid_tp:
        msg = f"No valid TP prices remain for {order_type.name} with SL={sl_price}"
        if ignore_invalid:
            tp_prices = []
        else:
            raise ValueError(msg)
    else:
        tp_prices = valid_tp

    # Apply limits
    if max_entries and len(entry_prices) > max_entries:
        entry_prices = entry_prices[:max_entries]
    if max_tps and len(tp_prices) > max_tps:
        tp_prices = tp_prices[:max_tps]

    # Logging
    logger.debug(
        "Price filtering completed",
        extra={
            **log_extra,
            "order_type": order_type.name,
            "sl": sl_price,
            "counts": {
                "entry": f"{len(entry_prices)}",
                "tp": f"{len(tp_prices)}",
            },
        },
    )

    return entry_prices, tp_prices
