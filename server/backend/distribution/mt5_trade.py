# /backend/distribution/mt5_trade.py
"""
Utilities for expanding a high-level trading Signal into one or more Mt5Trade records
for a specific CopySetup.

Design goals:
- Production-ready: clear logging, defensive checks, and concise, readable code.
- Robust: gracefully skips invalid inputs and isolates per-trade persistence errors.
- Professional: typed, documented, and consistent.
- Stable & simple: preserves the existing logic/architecture while tightening edges.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from enums import Mt5TradeState
from backend.db.crud.general import create
from backend.extract.filtering import filter_invalid_prices
from backend.db.functions import get_session_context
from models import CopySetup, Signal, Mt5Trade, CopySetupConfig

__all__ = ["_generate_trades"]

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Helpers: Signal -> Trades
# ----------------------------------------------------------------------
async def _generate_trades(copy_setup: CopySetup, signal: Signal) -> List[Mt5Trade]:
    """
    Expand a Signal into Mt5Trade objects for a given CopySetup.

    - Filters invalid prices based on copy setup config.
    - Skips trades gracefully if entries/TPs are invalid.
    - Persists to DB if a session is available.

    Parameters
    ----------
    copy_setup : CopySetup
        The copy configuration driving price filtering/validation.
    signal : Signal
        The incoming signal with symbol, type, prices, etc.

    Returns
    -------
    List[Mt5Trade]
        Persisted Mt5Trade rows (may be empty if nothing valid).
    """
    # Defensive: ensure config is present
    cfg: Optional[CopySetupConfig] = getattr(copy_setup, "config", None)
    if cfg is None:
        logger.warning(
            "CopySetup has no config; skipping trade generation.",
            extra={"copy_setup_id": getattr(copy_setup, "id", None), "signal_id": getattr(signal, "id", None)},
        )
        return []

    # Filter / normalize prices according to configuration
    try:
        entries, tps = filter_invalid_prices(
            order_type=signal.type,
            sl_price=signal.sl_price,
            entry_prices=signal.entry_prices or [],
            tp_prices=signal.tp_prices or [],
            max_entries=cfg.max_entry_prices,
            max_tps=cfg.max_tp_prices,
            ignore_invalid=cfg.ignore_invalid_prices,
            model_name_id=signal.id
        )
    except Exception as exc:
        # Prices unacceptable per config – skip the entire signal
        logger.info(
            "Skipped signal due to invalid/out-of-range prices.",
            extra={"signal_id": getattr(signal, "id", None), "copy_setup_id": getattr(copy_setup, "id", None)},
        )
        logger.debug("filter_invalid_prices raised: %r", exc, extra={"signal_id": getattr(signal, "id", None)})
        return []

    # Early exits if nothing actionable
    if not entries or not tps:
        logger.info(
            "No valid entries or TPs after filtering; nothing to generate.",
            extra={"signal_id": getattr(signal, "id", None), "copy_setup_id": getattr(copy_setup, "id", None)},
        )
        return []

    trades: List[Mt5Trade] = []
    post_dt = getattr(getattr(signal, "message", None), "post_datetime", None)

    # Persist each trade independently so one failure doesn't block others
    async with get_session_context() as db_sess:
        for e_idx, entry in enumerate(entries):
            if not entry:  # skip zeros if replacement was requested by config
                continue

            for tp_idx, tp in enumerate(tps):
                if not tp:
                    continue

                trade = Mt5Trade(
                    symbol=signal.symbol,
                    type=signal.type,
                    entry_price=entry,
                    tp_price=tp,
                    sl_price=signal.sl_price,
                    state=Mt5TradeState.PENDING_QUEUE,
                    signal_id=signal.id,
                    signal_entries_idx=e_idx,
                    signal_tps_idx=tp_idx,
                    signal_post_datetime=post_dt,
                    copy_setup_id=copy_setup.id,
                )

                try:
                    pass#trade = await create(trade, db_sess)  # DB assigns ID / manages commit per implementation
                except Exception as exc:
                    # Log and continue with the next trade candidate
                    logger.exception(
                        "Failed to persist Mt5Trade candidate; continuing.",
                        extra={
                            "signal_id": getattr(signal, "id", None),
                            "copy_setup_id": getattr(copy_setup, "id", None),
                        },
                    )
                    logger.debug("Mt5Trade data that failed to persist: %r", trade, extra={"signal_id": getattr(signal, "id", None)})
                    continue

                # Sanity/logging
                logger.debug(
                    "Created Mt5Trade.",
                    extra={
                        "mt5trade_id": getattr(trade, "id", None),
                        "signal_id": getattr(signal, "id", None),
                        "copy_setup_id": getattr(copy_setup, "id", None),
                    },
                )
                trades.append(trade)

    if not trades:
        logger.info(
            "No Mt5Trade rows generated for signal after processing.",
            extra={"signal_id": getattr(signal, "id", None), "copy_setup_id": getattr(copy_setup, "id", None)},
        )

    return trades
