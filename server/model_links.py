# model_links.py
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Index,
    MetaData,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


# Naming conventions help Alembic autogenerate stable, portable constraint names.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    metadata = metadata


# --- Association tables (many-to-many) ---

CopySetupTgChatLink = Table(
    "copy_setup_tg_chat_link",
    metadata,
    Column(
        "copy_setup_id",
        BigInteger,
        ForeignKey("copy_setups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tg_chat_id",
        BigInteger,
        ForeignKey("tg_chats.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    UniqueConstraint("copy_setup_id", "tg_chat_id", name="uq_copy_setup_tg_chat"),
    Index("ix_copy_setup_tg_chat_copy_setup_id", "copy_setup_id"),
    Index("ix_copy_setup_tg_chat_tg_chat_id", "tg_chat_id"),
)

Mt5TradeSignalReplyLink = Table(
    "mt5_trade_signal_reply_link",
    metadata,
    Column(
        "mt5_trade_id",
        BigInteger,
        ForeignKey("mt5_trades.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "signal_reply_id",
        BigInteger,
        ForeignKey("signal_replies.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    UniqueConstraint("mt5_trade_id", "signal_reply_id", name="uq_mt5_trade_signal_reply"),
    Index("ix_mt5_trade_signal_reply_trade_id", "mt5_trade_id"),
    Index("ix_mt5_trade_signal_reply_reply_id", "signal_reply_id"),
)

__all__ = [
    "Base",
    "metadata",
    "CopySetupTgChatLink",
    "Mt5TradeSignalReplyLink",
]
