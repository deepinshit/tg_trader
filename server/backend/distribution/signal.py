# /backend/distribution/signal.py

import logging
from typing import List, Optional, Sequence, Any

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
    Distribute a Signal to all sessions of all CopySetups in its chat.

    - Preloads relationships safely inside its own session.
    - Handles missing copy setups or sessions gracefully.
    - Failures per copy setup do not block others.
    """
    if signal is None:
        logger.warning("distribute_signal called with None signal.", extra={"signal_id": None})
        return

    # Preload signal with all required relationships
    try:
        async with get_session_context() as session:
            async with session.begin():
                stmt = (
                    select(Signal)
                    .options(
                        selectinload(Signal.message)
                        .selectinload(Message.tg_chat)
                        .selectinload(TgChat.copy_setups)
                        .selectinload(CopySetup.config)
                    )
                    .where(Signal.id == signal.id)
                )
                result = await session.execute(stmt)
                signal: Optional[Signal] = result.scalars().first()

        if not signal:
            logger.warning("Signal not found in DB.", extra={"signal_id": getattr(signal, "id", None)})
            return

        message: Optional[Message] = getattr(signal, "message", None)
        tg_chat: Optional[TgChat] = getattr(message, "tg_chat", None)
        copy_setups: Sequence[CopySetup] = getattr(tg_chat, "copy_setups", [])

        if not copy_setups:
            logger.info("No copy setups associated with signal; nothing to distribute.",
                        extra={"signal_id": signal.id})
            return

    except Exception as e:
        logger.exception("Failed to preload signal relationships.", extra={"signal_id": getattr(signal, "id", None)})
        return

    # Distribute to Redis
    async with RedisStore() as redis:
        for cs in copy_setups:
            cs_id: Optional[int] = getattr(cs, "id", None)
            try:
                sessions: List[Session] = await redis.get_sessions_by_copysetup(cs_id)
                if not sessions:
                    logger.debug("No active sessions for copy setup; skipping.",
                                 extra={"signal_id": signal.id, "copy_setup_id": cs_id})
                    continue

                trades = await _generate_trades(cs, signal)
                if not trades:
                    logger.debug("No trades generated for copy setup; skipping.",
                                 extra={"signal_id": signal.id, "copy_setup_id": cs_id})
                    continue

                trades_schemes: List[TradeScheme] = [create_trade_scheme(t) for t in trades]

                for sess in sessions:
                    await redis.add_pending_trades(sess.client_instance_id, trades_schemes)

                logger.info("Distributed %d trades to %d sessions.",
                            len(trades), len(sessions),
                            extra={"signal_id": signal.id, "copy_setup_id": cs_id})

            except Exception:
                logger.exception("Failed to distribute trades for copy setup.",
                                 extra={"signal_id": signal.id, "copy_setup_id": cs_id})
