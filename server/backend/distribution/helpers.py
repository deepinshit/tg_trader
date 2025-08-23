# /backend/distribution/helpers.py
"""
Lightweight helpers to convert DB models into public API schemes.

Design goals:
- Keep logic simple and focused on field mapping (no architectural changes).
- Be robust and production-friendly: validate inputs and emit structured logs.
- Remain stable and easy to extend if models/schemes evolve.

Logging:
- Uses `extra` to attach `<model_name>_id` to each record for traceability.
"""

from __future__ import annotations

import logging

from models import Mt5Trade, SignalReply
from api.schemes import Trade, SignalReply as SignalReplyScheme

__all__ = ["create_trade_scheme", "create_signal_reply_scheme"]

logger = logging.getLogger(__name__)


def create_trade_scheme(mt5_trade: Mt5Trade) -> Trade:
    """
    Convert a Mt5Trade DB model into an API Trade scheme.

    Args:
        mt5_trade (Mt5Trade): Database Mt5Trade instance. Must not be None.

    Returns:
        Trade: API Trade scheme instance.

    Raises:
        ValueError: If `mt5_trade` is None.
        Exception: Any unexpected error during mapping is logged and re-raised.
    """
    if mt5_trade is None:
        # Respect the requirement to log with `extra` and include related model id key.
        logger.error(
            "create_trade_scheme called with None.",
            extra={"mt5_trade_id": None},
        )
        raise ValueError("mt5_trade must not be None")

    try:
        scheme = Trade(
            id=mt5_trade.id,
            ticket=mt5_trade.ticket,
            symbol=mt5_trade.symbol,
            type=mt5_trade.type,
            state=mt5_trade.state,
            sl_price=mt5_trade.sl_price,
            entry_price=mt5_trade.entry_price,
            tp_price=mt5_trade.tp_price,
            signal_tps_idx=mt5_trade.signal_tps_idx,
            signal_entries_idx=mt5_trade.signal_entries_idx,
            signal_post_datetime=mt5_trade.signal_post_datetime,
            close_reason=mt5_trade.close_reason,
            expire_reason=mt5_trade.expire_reason,
            modified_sl=mt5_trade.modified_sl,
            open_price=mt5_trade.open_price,
            open_datetime=mt5_trade.open_datetime,
            volume=mt5_trade.volume,
            pnl=mt5_trade.pnl,
            swap=mt5_trade.swap,
            commission=mt5_trade.commission,
            fee=mt5_trade.fee,
            close_price=mt5_trade.close_price,
            close_datetime=mt5_trade.close_datetime,
            created_at=mt5_trade.created_at,
            updated_at=mt5_trade.updated_at,
        )
        logger.debug(
            "Converted Mt5Trade -> Trade scheme.",
            extra={"mt5_trade_id": getattr(mt5_trade, "id", None)},
        )
        return scheme
    except Exception:
        # Ensure failures are observable with relevant context, then bubble up.
        logger.exception(
            "Failed converting Mt5Trade -> Trade scheme.",
            extra={"mt5_trade_id": getattr(mt5_trade, "id", None)},
        )
        raise


def create_signal_reply_scheme(signal_reply: SignalReply) -> SignalReplyScheme:
    """
    Convert a SignalReply DB model into an API SignalReply scheme.

    Args:
        signal_reply (SignalReply): Database SignalReply instance. Must not be None.

    Returns:
        SignalReplyScheme: API SignalReply scheme instance.

    Raises:
        ValueError: If `signal_reply` is None.
        Exception: Any unexpected error during mapping is logged and re-raised.
    """
    if signal_reply is None:
        logger.error(
            "create_signal_reply_scheme called with None.",
            extra={"signal_reply_id": None},
        )
        raise ValueError("signal_reply must not be None")

    try:
        scheme = SignalReplyScheme(
            id=signal_reply.id,
            action=signal_reply.action,
            generated_by=signal_reply.generated_by,
            info_message=signal_reply.info_message,
            original_signal_id=signal_reply.original_signal_id,
            created_at=signal_reply.created_at,
        )
        logger.debug(
            "Converted SignalReply -> SignalReply scheme.",
            extra={"signal_reply_id": getattr(signal_reply, "id", None)},
        )
        return scheme
    except Exception:
        logger.exception(
            "Failed converting SignalReply -> SignalReply scheme.",
            extra={"signal_reply_id": getattr(signal_reply, "id", None)},
        )
        raise
