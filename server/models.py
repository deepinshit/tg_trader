# models.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    Enum as PgEnum,
    ForeignKey,
    Index,
    Numeric,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from helpers import utc_now
from model_links import Base, CopySetupTgChatLink, Mt5TradeSignalReplyLink
from enums import (
    OrderType,
    SignalReplyAction,
    SignalReplyGeneratedBy,
    Mt5TradeState,
    Mt5TradeCloseReason,
    Mt5TradeExpireReason,
    LotMode,
    MultipleTPMode,
    MultipleEntryMode,
    TgChatType,
    UserRole
)


# --------------------
# Helper column factories
# --------------------
def BIGINT_PK():
    return mapped_column(BigInteger, primary_key=True, autoincrement=True)


def BIGINT_FK(
    target: str,
    *,
    nullable: bool = True,
    ondelete: Optional[str] = None,
):
    return mapped_column(BigInteger, ForeignKey(target, ondelete=ondelete), nullable=nullable)


# --------------------
# Models
# --------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = BIGINT_PK()
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False, index=True)
    username: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    role: Mapped[UserRole] = mapped_column(PgEnum(UserRole, name="user_role"), nullable=False)

    copy_setups: Mapped[List["CopySetup"]] = relationship(
        back_populates="user",
        cascade="save-update, merge",
        lazy="selectin",
    )
    copy_setup_configs: Mapped[List["CopySetupConfig"]] = relationship(
        back_populates="user",
        cascade="save-update, merge",
        lazy="selectin",
    )
    logs: Mapped[List["Log"]] = relationship(
        back_populates="user",
        cascade="save-update, merge",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, email={self.email!r})"


class TgChat(Base):
    __tablename__ = "tg_chats"

    id: Mapped[int] = BIGINT_PK()
    title: Mapped[str] = mapped_column(nullable=False)
    username: Mapped[Optional[str]] = mapped_column(nullable=True)
    chat_type: Mapped[TgChatType] = mapped_column(PgEnum(TgChatType, name="tg_chat_type"), nullable=False)

    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)

    messages: Mapped[List["Message"]] = relationship(
        back_populates="tg_chat",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    # many-to-many with CopySetup via association table
    copy_setups: Mapped[List["CopySetup"]] = relationship(
        back_populates="tg_chats",
        secondary=CopySetupTgChatLink,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"TgChat(id={self.id!r}, title={self.title!r}, type={self.chat_type!r})"


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = BIGINT_PK()
    symbol: Mapped[str] = mapped_column(nullable=False, index=True)
    type: Mapped[OrderType] = mapped_column(PgEnum(OrderType, name="order_type"), nullable=False)

    # Stored as DECIMAL in DB for precision, typed as List[float] for ease-of-use.
    entry_prices: Mapped[List[float]] = mapped_column(ARRAY(Numeric(20, 10)), nullable=False)
    tp_prices: Mapped[List[float]] = mapped_column(ARRAY(Numeric(20, 10)), nullable=False)
    sl_price: Mapped[float] = mapped_column(Numeric(20, 10), nullable=False)

    max_tp_hit: Mapped[Optional[int]] = mapped_column(nullable=True)
    sl_hit: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    tps_hit: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    entries_hit: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)

    message: Mapped[Optional["Message"]] = relationship(back_populates="signal", uselist=False, lazy="selectin")
    replies: Mapped[List["SignalReply"]] = relationship(
        back_populates="original_signal",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    mt5_trades: Mapped[List["Mt5Trade"]] = relationship(
        back_populates="signal",
        cascade="save-update, merge",
        lazy="selectin",
    )
    logs: Mapped[List["Log"]] = relationship(
        back_populates="signal",
        cascade="save-update, merge",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_signals_symbol_created", "symbol", "created_at"),
    )

    def __repr__(self) -> str:
        return f"Signal(id={self.id!r}, symbol={self.symbol!r}, type={self.type!r})"


class SignalReply(Base):
    __tablename__ = "signal_replies"

    id: Mapped[int] = BIGINT_PK()
    action: Mapped[SignalReplyAction] = mapped_column(PgEnum(SignalReplyAction, name="signal_reply_action"), nullable=False)
    generated_by: Mapped[SignalReplyGeneratedBy] = mapped_column(
        PgEnum(SignalReplyGeneratedBy, name="signal_reply_generated_by"),
        nullable=False,
    )
    info_message: Mapped[Optional[str]] = mapped_column(nullable=True)

    original_signal_id: Mapped[Optional[int]] = BIGINT_FK("signals.id", ondelete="SET NULL")
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)

    original_signal: Mapped[Optional["Signal"]] = relationship(back_populates="replies", lazy="selectin")
    message: Mapped[Optional["Message"]] = relationship(back_populates="signal_reply", uselist=False, lazy="selectin")

    # many-to-many with Mt5Trade
    mt5_trades: Mapped[List["Mt5Trade"]] = relationship(
        back_populates="signal_replies",
        secondary=Mt5TradeSignalReplyLink,
        lazy="selectin",
    )
    logs: Mapped[List["Log"]] = relationship(
        back_populates="signal_reply",
        cascade="save-update, merge",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"SignalReply(id={self.id!r}, action={self.action!r}, by={self.generated_by!r})"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = BIGINT_PK()
    tg_chat_id: Mapped[int] = BIGINT_FK("tg_chats.id", nullable=False, ondelete="CASCADE")
    tg_msg_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    text: Mapped[str] = mapped_column(nullable=False)
    post_datetime: Mapped[datetime] = mapped_column(nullable=False)

    signal_id: Mapped[Optional[int]] = BIGINT_FK("signals.id", ondelete="SET NULL")
    signal_reply_id: Mapped[Optional[int]] = BIGINT_FK("signal_replies.id", ondelete="SET NULL")

    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)

    tg_chat: Mapped["TgChat"] = relationship(back_populates="messages", lazy="selectin")
    signal: Mapped[Optional["Signal"]] = relationship(back_populates="message", lazy="selectin")
    signal_reply: Mapped[Optional["SignalReply"]] = relationship(back_populates="message", lazy="selectin")
    logs: Mapped[List["Log"]] = relationship(
        back_populates="message",
        cascade="save-update, merge",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_messages_tgchatid_msgid", "tg_chat_id", "tg_msg_id"),
    )

    def __repr__(self) -> str:
        return f"Message(id={self.id!r}, tg_chat_id={self.tg_chat_id!r}, tg_msg_id={self.tg_msg_id!r})"


class CopySetupConfig(Base):
    __tablename__ = "copy_setup_configs"

    id: Mapped[int] = BIGINT_PK()
    user_id: Mapped[int] = BIGINT_FK("users.id", nullable=False, ondelete="CASCADE")

    name: Mapped[str] = mapped_column(default="custom config", nullable=False)
    allowed_symbols: Mapped[Optional[str]] = mapped_column(nullable=True)
    symbol_synonyms_mapping: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    lot_mode: Mapped[LotMode] = mapped_column(PgEnum(LotMode, name="lot_mode"), nullable=False, default=LotMode.AUTO)
    fixed_lot: Mapped[Optional[float]] = mapped_column(Numeric(20, 10), nullable=True)
    max_price_range_perc: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    max_risk_perc_from_equity_per_signal: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    multiple_tp_mode: Mapped[MultipleTPMode] = mapped_column(
        PgEnum(MultipleTPMode, name="multiple_tp_mode"), nullable=False, default=MultipleTPMode.ALL
    )
    multiple_entry_mode: Mapped[MultipleEntryMode] = mapped_column(
        PgEnum(MultipleEntryMode, name="multiple_entry_mode"), nullable=False, default=MultipleEntryMode.ALL
    )

    close_on_signal_reply: Mapped[bool] = mapped_column(default=False, nullable=False)
    modify_on_signal_reply: Mapped[bool] = mapped_column(default=False, nullable=False)
    close_on_msg_delete: Mapped[bool] = mapped_column(default=False, nullable=False)
    ignore_prices_out_of_range: Mapped[bool] = mapped_column(default=True, nullable=False)
    breakeven_on_tp_layer: Mapped[Optional[int]] = mapped_column(nullable=True)
    close_trades_before_everyday_swap: Mapped[bool] = mapped_column(default=False, nullable=False)
    close_trades_before_wednesday_swap: Mapped[bool] = mapped_column(default=False, nullable=False)
    close_trades_before_weekend: Mapped[bool] = mapped_column(default=False, nullable=False)
    trailingstop_on_tps: Mapped[bool] = mapped_column(default=False, nullable=False)
    tradeprofit_percent_from_balans_for_breakeven: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    expire_minutes_pending_trade: Mapped[Optional[int]] = mapped_column(nullable=True)
    expire_minutes_active_trade: Mapped[Optional[int]] = mapped_column(nullable=True)
    expire_at_tp_hit_before_entry: Mapped[Optional[int]] = mapped_column(nullable=True)
    follow_tp_and_sl_hits_from_others: Mapped[bool] = mapped_column(default=False, nullable=False)

    user: Mapped["User"] = relationship(back_populates="copy_setup_configs", lazy="selectin")
    copy_setups: Mapped[List["CopySetup"]] = relationship(
        back_populates="config",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"CopySetupConfig(id={self.id!r}, user_id={self.user_id!r})"


class CopySetup(Base):
    __tablename__ = "copy_setups"

    id: Mapped[int] = BIGINT_PK()
    user_id: Mapped[int] = BIGINT_FK("users.id", nullable=False, ondelete="CASCADE")
    config_id: Mapped[int] = BIGINT_FK("copy_setup_configs.id", nullable=False, ondelete="CASCADE")
    cs_token: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    
    user: Mapped["User"] = relationship(back_populates="copy_setups", lazy="selectin")
    config: Mapped["CopySetupConfig"] = relationship(back_populates="copy_setups", lazy="selectin")

    # many-to-many with TgChat
    tg_chats: Mapped[List["TgChat"]] = relationship(
        back_populates="copy_setups",
        secondary=CopySetupTgChatLink,
        lazy="selectin",
    )

    mt5_trades: Mapped[List["Mt5Trade"]] = relationship(
        back_populates="copy_setup",
        cascade="save-update, merge",
        lazy="selectin",
    )
    logs: Mapped[List["Log"]] = relationship(
        back_populates="copy_setup",
        cascade="save-update, merge",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"CopySetup(id={self.id!r}, user_id={self.user_id!r}, active={self.active!r})"


class Mt5Trade(Base):
    __tablename__ = "mt5_trades"

    id: Mapped[int] = BIGINT_PK()
    ticket: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(nullable=False, index=True)
    type: Mapped[OrderType] = mapped_column(PgEnum(OrderType, name="mt5_order_type"), nullable=False)
    state: Mapped[Mt5TradeState] = mapped_column(PgEnum(Mt5TradeState, name="mt5_trade_state"), nullable=False)

    entry_price: Mapped[float] = mapped_column(Numeric(20, 10), nullable=False)
    sl_price: Mapped[float] = mapped_column(Numeric(20, 10), nullable=False)
    tp_price: Mapped[float] = mapped_column(Numeric(20, 10), nullable=False)
    volume: Mapped[Optional[float]] = mapped_column(Numeric(20, 10), nullable=True)
    pnl: Mapped[Optional[float]] = mapped_column(Numeric(20, 10), nullable=True)
    swap: Mapped[Optional[float]] = mapped_column(Numeric(20, 10), nullable=True)
    commission: Mapped[Optional[float]] = mapped_column(Numeric(20, 10), nullable=True)
    fee: Mapped[Optional[float]] = mapped_column(Numeric(20, 10), nullable=True)
    close_price: Mapped[Optional[float]] = mapped_column(Numeric(20, 10), nullable=True)

    signal_post_datetime: Mapped[datetime] = mapped_column(nullable=False)
    signal_tps_idx: Mapped[int] = mapped_column(nullable=False)
    signal_entries_idx: Mapped[int] = mapped_column(nullable=False)

    close_reason: Mapped[Optional[Mt5TradeCloseReason]] = mapped_column(
        PgEnum(Mt5TradeCloseReason, name="mt5_trade_close_reason"),
        nullable=True,
    )
    expire_reason: Mapped[Optional[Mt5TradeExpireReason]] = mapped_column(
        PgEnum(Mt5TradeExpireReason, name="mt5_trade_expire_reason"),
        nullable=True,
    )
    modified_sl: Mapped[Optional[float]] = mapped_column(Numeric(20, 10), nullable=True)
    open_price: Mapped[Optional[float]] = mapped_column(Numeric(20, 10), nullable=True)
    open_datetime: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    close_datetime: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    signal_id: Mapped[Optional[int]] = BIGINT_FK("signals.id", ondelete="SET NULL")
    copy_setup_id: Mapped[Optional[int]] = BIGINT_FK("copy_setups.id", ondelete="CASCADE")

    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now, nullable=False)

    signal: Mapped[Optional["Signal"]] = relationship(back_populates="mt5_trades", lazy="selectin")
    copy_setup: Mapped[Optional["CopySetup"]] = relationship(back_populates="mt5_trades", lazy="selectin")

    # many-to-many with SignalReply
    signal_replies: Mapped[List["SignalReply"]] = relationship(
        back_populates="mt5_trades",
        secondary=Mt5TradeSignalReplyLink,
        lazy="selectin",
    )

    logs: Mapped[List["Log"]] = relationship(
        back_populates="mt5_trade",
        cascade="save-update, merge",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_mt5trade_symbol_ticket", "symbol", "ticket"),
    )

    def __repr__(self) -> str:
        return f"Mt5Trade(id={self.id!r}, ticket={self.ticket!r}, symbol={self.symbol!r}, state={self.state!r})"


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[int] = BIGINT_PK()
    created_at: Mapped[datetime] = mapped_column(default=utc_now, nullable=False, index=True)
    context: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    user_id: Mapped[Optional[int]] = BIGINT_FK("users.id", ondelete="SET NULL")
    copy_setup_id: Mapped[Optional[int]] = BIGINT_FK("copy_setups.id", ondelete="SET NULL")
    signal_id: Mapped[Optional[int]] = BIGINT_FK("signals.id", ondelete="SET NULL")
    mt5_trade_id: Mapped[Optional[int]] = BIGINT_FK("mt5_trades.id", ondelete="SET NULL")
    message_id: Mapped[Optional[int]] = BIGINT_FK("messages.id", ondelete="SET NULL")
    signal_reply_id: Mapped[Optional[int]] = BIGINT_FK("signal_replies.id", ondelete="SET NULL")

    user: Mapped[Optional["User"]] = relationship(back_populates="logs", lazy="selectin")
    copy_setup: Mapped[Optional["CopySetup"]] = relationship(back_populates="logs", lazy="selectin")
    signal: Mapped[Optional["Signal"]] = relationship(back_populates="logs", lazy="selectin")
    mt5_trade: Mapped[Optional["Mt5Trade"]] = relationship(back_populates="logs", lazy="selectin")
    message: Mapped[Optional["Message"]] = relationship(back_populates="logs", lazy="selectin")
    signal_reply: Mapped[Optional["SignalReply"]] = relationship(back_populates="logs", lazy="selectin")

    def __repr__(self) -> str:
        return f"Log(id={self.id!r}, created_at={self.created_at!r})"
