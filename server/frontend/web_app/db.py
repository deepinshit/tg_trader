# frontend/web_app/db.py
from __future__ import annotations
from typing import Iterable, Sequence, Optional, List, Dict, Any, Tuple
from datetime import datetime

from backend.db.functions import AsyncSession
from models import (
    User, CopySetupConfig, CopySetup, TgChat, Message, Signal
)

# ------------- Copy Setup Configs -------------

async def list_copy_setup_configs_for_user(
    db: AsyncSession, user: User
) -> Sequence[CopySetupConfig]:
    """Return all CopySetupConfig rows owned by user, newest first."""
    raise NotImplementedError

async def create_copy_setup_config(
    db: AsyncSession,
    user: User,
    *,
    allowed_symbols: Optional[str],
    symbol_synonyms_mapping: Dict[str, Any],
    lot_mode: str,
    fixed_lot: Optional[float],
    max_price_range_perc: Optional[float],
    multiple_tp_mode: str,
    multiple_entry_mode: str,
    close_on_signal_reply: bool,
    modify_on_signal_reply: bool,
    close_on_msg_delete: bool,
    close_on_new_signal_same_symbol: bool,
    ignore_prices_out_of_range: bool,
    breakeven_on_tp_layer: Optional[int],
    close_trades_before_everyday_swap: bool,
    close_trades_before_wednesday_swap: bool,
    close_trades_before_weekend: bool,
    trailingstop_on_tps: bool,
    tradeprofit_percent_from_balans_for_breakeven: Optional[float],
    expire_minutes_pending_trade: Optional[int],
    expire_minutes_active_trade: Optional[int],
    expire_at_tp_hit_before_entry: Optional[int],
    follow_tp_and_sl_hits_from_others: bool,
    keep_managing_when_not_active: bool,
) -> CopySetupConfig:
    """Insert a CopySetupConfig for user. Cast string enums to your Enum types here."""
    raise NotImplementedError

# ------------- Copy Setups -------------

async def list_copy_setups_for_user(
    db: AsyncSession, user: User
) -> Sequence[CopySetup]:
    """Return all CopySetup rows for user, newest first, eager-loading config & tg_chats."""
    raise NotImplementedError

async def create_copy_setup(
    db: AsyncSession,
    user: User,
    *,
    config_id: int,
    cs_token: str,
    active: bool,
    tg_chat_ids: Optional[List[int]],
) -> CopySetup:
    """
    Create a CopySetup owned by user, linking optional TgChats by IDs.
    Ensure the config_id belongs to the same user.
    """
    raise NotImplementedError

async def get_copy_setup_with_relations(
    db: AsyncSession,
    user: User,
    setup_id: int
) -> Optional[CopySetup]:
    """Return a single CopySetup for user with config & tg_chats. None if not found or not owned."""
    raise NotImplementedError

async def list_recent_messages_for_setup_chats(
    db: AsyncSession,
    setup: CopySetup,
    limit: int = 200
) -> Sequence[Message]:
    """
    Return last N messages for all chats linked to the setup,
    eager-loading .signal and .signal_reply for rendering.
    """
    raise NotImplementedError

# ------------- Telegram Chats -------------

async def list_tg_chats_for_user_overview(
    db: AsyncSession, user: User
) -> Sequence[TgChat]:
    """
    Return chats relevant to the user (all or restricted, your call).
    For now you can return all. Eager-load messages count cheaply if you want.
    """
    raise NotImplementedError

async def get_tg_chat(
    db: AsyncSession, user: User, chat_id: int
) -> Optional[TgChat]:
    """Return a single TgChat (optionally enforce user access)."""
    raise NotImplementedError

async def list_recent_messages_for_chat(
    db: AsyncSession,
    chat: TgChat,
    limit: int = 200
) -> Sequence[Message]:
    """Return last N messages for a chat, eager-loading .signal and .signal_reply."""
    raise NotImplementedError

# ------------- Dashboard -------------

async def get_dashboard_summary(
    db: AsyncSession, user: User, *, chats_limit: int = 5, setups_limit: int = 6
) -> Tuple[Sequence[CopySetup], Sequence[TgChat]]:
    """
    Return (copy_setups, top_chats) for the dashboard.
    Implement 'top_chats' as chats with most signals/messages recently.
    """
    raise NotImplementedError
