# /backend/distribution/signal.py
import logging
from typing import List, Sequence, Optional, Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.schemes import Session, Trade as TradeScheme
from backend.redis.store import RedisStore
from models import Signal, Message, CopySetup, TgChat
from backend.distribution.mt5_trade import _generate_trades
from backend.distribution.helpers import create_trade_scheme
from backend.db.functions import get_session_context

__all__ = ["distribute_signal"]

logger = logging.getLogger(__name__)


async def distribute_signal(signal: Signal) -> None:
    """
    Distribute a trading Signal into Redis pending queues as Trade schemes
    for all Sessions of all CopySetups attached to the Signal's chat.

    Behavior & Constraints
    ----------------------
    - Does not alter the existing logic or architecture.
    - Gracefully handles empty/missing copy setups, sessions, or generated trades.
    - Logs with `extra` to include related model IDs as `{model_name}_id`.
    - Fails *per copy setup* without aborting distribution for others.

    Parameters
    ----------
    signal : Signal
        The domain Signal instance to distribute.

    Returns
    -------
    None
    """
    if signal is None:
        # Defensive guard; shouldn't normally happen.
        logger.warning(
            "distribute_signal invoked with None signal.",
            extra={"signal_id": None},
        )
        return
    
    async with get_session_context() as session:
        stmt = (
            select(Signal)
            .options(
                selectinload(Signal.message).selectinload(Message.tg_chat)
                .selectinload(TgChat.copy_setups).selectinload(CopySetup.config)
            )
            .where(Signal.id == signal.id)  # or whatever identifier you have
        )
        result = await session.execute(stmt)
        signal: Signal | None = result.scalars().first()

    # Resolve copy setups defensively to avoid AttributeErrors if any linkage is missing.
    copy_setups: Sequence[Any] = []
    try:
        # Expected chain: signal.message.tg_chat.copy_setups
        message = getattr(signal, "message", None)
        tg_chat = getattr(message, "tg_chat", None)
        copy_setups = getattr(tg_chat, "copy_setups", [])
    except Exception:
        logger.exception(
            "Failed to resolve copy setups for signal.",
            extra={"signal_id": getattr(signal, "id", None)},
        )
        return

    if not copy_setups:
        logger.info(
            "No copy setups associated with signal; nothing to distribute.",
            extra={"signal_id": getattr(signal, "id", None)},
        )
        return

    async with RedisStore() as redis:
        for cs in copy_setups:
            cs_id: Optional[int] = getattr(cs, "id", None)
            try:
                # Resolve sessions for this copy setup.
                sessions: List[Session] = await redis.get_sessions_for_copysetup(cs_id)
                if not sessions:
                    logger.debug(
                        "No active sessions for copy setup; skipping.",
                        extra={
                            "signal_id": getattr(signal, "id", None),
                            "copy_setup_id": cs_id,
                        },
                    )
                    continue

                # Generate trades for this copy setup + signal.
                trades = await _generate_trades(cs, signal)
                if not trades:
                    logger.debug(
                        "No trades generated for copy setup; skipping.",
                        extra={
                            "signal_id": getattr(signal, "id", None),
                            "copy_setup_id": cs_id,
                        },
                    )
                    continue

                # Convert to API schemes once and reuse for all sessions.
                trades_schemes: List[TradeScheme] = [create_trade_scheme(t) for t in trades]

                # Enqueue for each session.
                for sess in sessions:
                    await redis.add_pending_trades(sess.client_instance_id, trades_schemes)

                logger.info(
                    "Distributed %d trades to %d sessions.",
                    len(trades),
                    len(sessions),
                    extra={
                        "signal_id": getattr(signal, "id", None),
                        "copy_setup_id": cs_id,
                    },
                )

            except Exception:
                # Catch-all to avoid blocking other copy setups.
                logger.exception(
                    "Failed to distribute trades for copy setup.",
                    extra={
                        "signal_id": getattr(signal, "id", None),
                        "copy_setup_id": cs_id,
                    },
                )
