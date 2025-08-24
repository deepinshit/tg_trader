# /backend/extract/extract_models.py
"""
Pydantic models used by the extract layer.

Goals:
- Production-ready, robust, and clean.
- Pydantic v2 only (no legacy compatibility).
- Explicit validation rules with helpful error messages.
- Scalable and flexible, yet stable.
- Includes helper for structured logging with model IDs.

Notes:
- List fields in `SignalBase` must be non-empty and aligned by index.
- Price fields must be finite, positive numbers.
- For `SignalReplyBase`, when action == "MODIFY_SL", `new_sl_price` must be provided.
"""

from __future__ import annotations

import math
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from enums import OrderType


__all__ = ["SignalReplyBase", "SignalBase"]



# -------------------------
# Models
# -------------------------

class SignalReplyBase(BaseModel):
    """
    Outbound reply for a trading signal action.

    Fields:
        action: One of "NONE", "BREAKEVEN", "MODIFY_SL", "CLOSE".
        info_message: Human-readable context to accompany the action.
        new_sl_price: New stop-loss price, required when action == "MODIFY_SL".
    """

    action: Literal["NONE", "BREAKEVEN", "MODIFY_SL", "CLOSE"] = Field(
        ..., description="Action to apply to the signal."
    )
    info_message: str = Field(
        ..., description="Human-readable context about the action."
    )
    new_sl_price: Optional[float] = Field(
        default=None,
        description="New stop-loss price. Required when action == 'MODIFY_SL'.",
    )


class SignalBase(BaseModel):
    """
    Core payload describing trading signal candidates.

    Fields:
        symbols: Instrument symbols (aligned by index with prices/types).
        types: Order types (aligned with symbols).
        entry_prices: Entry prices (aligned with symbols).
        tp_prices: Take-profit prices (aligned with symbols).
        sl_prices: Stop-loss prices (aligned with symbols).
        info_message: Human-readable context for the group of items.

    Invariants:
        - All list fields must be non-empty.
        - All list fields must have identical lengths.
        - Prices must be positive, finite numbers.
    """

    symbols: List[str] = Field(..., description="Instrument symbols.")
    types: List[Union[OrderType, Literal["BUY", "SELL"]]] = Field(..., description="Order types for each symbol.")
    entry_prices: List[float] = Field(..., description="Entry prices per symbol.")
    tp_prices: List[float] = Field(..., description="Take-profit prices per symbol.")
    sl_prices: List[float] = Field(..., description="Stop-loss prices per symbol.")
    info_message: str = Field(..., description="Context/notes about this signal batch.")

    

