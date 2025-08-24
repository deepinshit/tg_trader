# models.py
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypeVar

try:
    from typing_extensions import dataclass_transform
except ImportError:
    from typing import dataclass_transform

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Enum as PgEnum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from helpers import utc_now

if TYPE_CHECKING:
    from enums import (
        LotMode,
        Mt5TradeCloseReason,
        Mt5TradeExpireReason,
        Mt5TradeState,
        MultipleEntryMode,
        MultipleTPMode,
        OrderType,
        SignalReplyAction,
        SignalReplyGeneratedBy,
        TgChatType,
        UserRole,
    )
else:
    # Import enums for runtime usage
    from enums import (
        LotMode,
        Mt5TradeCloseReason,
        Mt5TradeExpireReason,
        Mt5TradeState,
        MultipleEntryMode,
        MultipleTPMode,
        OrderType,
        SignalReplyAction,
        SignalReplyGeneratedBy,
        TgChatType,
        UserRole,
    )


# Naming conventions help Alembic autogenerate stable, portable constraint names
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


T = TypeVar("T", bound="Base")


@dataclass_transform(kw_only_default=True)
class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models with extra utilities."""
    
    __abstract__ = True  # Do not create a table for Base
    metadata = metadata

    def to_dict(self) -> Dict[str, Any]:
        """Convert model into a dict, excluding internal attributes."""
        mapper = inspect(self.__class__)
        return {attr.key: getattr(self, attr.key) for attr in mapper.attrs}

    def to_json(self) -> str:
        """Return JSON representation of the model."""
        return json.dumps(self.to_dict(), default=str)

    def copy(self: T, **overrides) -> T:
        """
        Create a shallow copy of the model with optional field overrides.
        Does NOT include primary keys or relationships by default.
        """
        data = self.to_dict()
        # Remove primary keys if they exist
        for pk in inspect(self.__class__).primary_key:
            data.pop(pk.name, None)
        data.update(overrides)
        return self.__class__(**data)

    def clone(self: T, **overrides) -> T:
        """Clone including primary key values."""
        data = self.to_dict()
        data.update(overrides)
        return self.__class__(**data)

    def __repr__(self) -> str:
        values = ", ".join(f"{k}={v!r}" for k, v in self.to_dict().items())
        return f"<{self.__class__.__name__}({values})>"


# -------------------- 
# Helper column factories
# -------------------- 

def BIGINT_PK() -> Mapped[int]:
    """Create a BigInteger primary key column."""
    return mapped_column(
        BigInteger, 
        primary_key=True, 
        autoincrement=True,
        nullable=False
    )


def BIGINT_FK(
    target: str, 
    *, 
    nullable: bool = True, 
    ondelete: Optional[str] = None,
) -> Mapped[Optional[int]] | Mapped[int]:
    """Create a BigInteger foreign key column."""
    return mapped_column(
        BigInteger, 
        ForeignKey(target, ondelete=ondelete), 
        nullable=nullable
    )


def DATETIME_NOW() -> Mapped[datetime]:
    """Create a datetime column with default UTC now."""
    return mapped_column(
        nullable=False, 
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP")
    )


def DATETIME_AUTO_UPDATE() -> Mapped[datetime]:
    """Create a datetime column that auto-updates on modification."""
    return mapped_column(
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP")
    )


def JSONB_DICT() -> Mapped[Dict[str, Any]]:
    """Create a JSONB column for dictionaries."""
    return mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb")
    )


def DECIMAL_PRICE() -> Mapped[Decimal]:
    """Create a high-precision decimal column for prices."""
    return mapped_column(Numeric(20, 10), nullable=False)


def DECIMAL_PRICE_OPTIONAL() -> Mapped[Optional[Decimal]]:
    """Create an optional high-precision decimal column for prices."""
    return mapped_column(Numeric(20, 10), nullable=True)


def PERCENTAGE() -> Mapped[Optional[Decimal]]:
    """Create a percentage column (5,2 precision)."""
    return mapped_column(Numeric(5, 2), nullable=True)


def ARRAY_DECIMAL() -> Mapped[List[Decimal]]:
    """Create an array of decimal values."""
    return mapped_column(ARRAY(Numeric(20, 10)), nullable=False)


# -------------------- 
# Models
# -------------------- 

class User(Base):
    __tablename__ = "users"
    
    # Primary key
    id: Mapped[int] = BIGINT_PK()
    
    # Core fields
    created_at: Mapped[datetime] = DATETIME_NOW()
    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(PgEnum(UserRole, name="user_role"), nullable=False)
    
    # Relationships
    copy_setups: Mapped[List[CopySetup]] = relationship(
        back_populates="user",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="selectin",
    )
    
    copy_setup_configs: Mapped[List[CopySetupConfig]] = relationship(
        back_populates="user",
        cascade="save-update, merge", 
        passive_deletes=True,
        lazy="selectin",
    )
    
    logs: Mapped[List[Log]] = relationship(
        back_populates="user",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="select",
    )
    
    def __repr__(self) -> str:
        return f"User(id={self.id!r}, email={self.email!r})"


class TgChat(Base):
    __tablename__ = "tg_chats"
    
    # Primary key  
    id: Mapped[int] = BIGINT_PK()
    
    # Core fields
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    chat_type: Mapped[TgChatType] = mapped_column(PgEnum(TgChatType, name="tg_chat_type"), nullable=False)
    created_at: Mapped[datetime] = DATETIME_NOW()
    updated_at: Mapped[datetime] = DATETIME_AUTO_UPDATE()
    
    # Relationships
    messages: Mapped[List[Message]] = relationship(
        back_populates="tg_chat",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    
    copy_setups: Mapped[List[CopySetup]] = relationship(
        back_populates="tg_chats",
        secondary="copy_setup_tg_chat_link",
        lazy="selectin",
    )
    
    def __repr__(self) -> str:
        return f"TgChat(id={self.id!r}, title={self.title!r}, type={self.chat_type!r})"


class Signal(Base):
    __tablename__ = "signals"
    
    # Primary key
    id: Mapped[int] = BIGINT_PK()
    
    # Core fields
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    type: Mapped[OrderType] = mapped_column(PgEnum(OrderType, name="order_type"), nullable=False)
    entry_prices: Mapped[List[Decimal]] = ARRAY_DECIMAL()
    tp_prices: Mapped[List[Decimal]] = ARRAY_DECIMAL() 
    sl_price: Mapped[Decimal] = DECIMAL_PRICE()
    
    # Status tracking
    max_tp_hit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sl_hit: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    tps_hit: Mapped[Dict[str, Any]] = JSONB_DICT()
    entries_hit: Mapped[Dict[str, Any]] = JSONB_DICT()
    
    # Timestamps
    created_at: Mapped[datetime] = DATETIME_NOW()
    updated_at: Mapped[datetime] = DATETIME_AUTO_UPDATE()
    
    # Relationships
    message: Mapped[Optional[Message]] = relationship(
        back_populates="signal", 
        uselist=False,
        lazy="selectin",
    )
    
    replies: Mapped[List[SignalReply]] = relationship(
        back_populates="original_signal",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    
    mt5_trades: Mapped[List[Mt5Trade]] = relationship(
        back_populates="signal",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="selectin",
    )
    
    logs: Mapped[List[Log]] = relationship(
        back_populates="signal",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="select",
    )
    
    __table_args__ = (
        Index("idx_signals_symbol_created", "symbol", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"Signal(id={self.id!r}, symbol={self.symbol!r}, type={self.type!r})"


class SignalReply(Base):
    __tablename__ = "signal_replies"
    
    # Primary key
    id: Mapped[int] = BIGINT_PK()
    
    # Core fields
    action: Mapped[SignalReplyAction] = mapped_column(
        PgEnum(SignalReplyAction, name="signal_reply_action"), 
        nullable=False
    )
    generated_by: Mapped[SignalReplyGeneratedBy] = mapped_column(
        PgEnum(SignalReplyGeneratedBy, name="signal_reply_generated_by"),
        nullable=False
    )
    info_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = DATETIME_NOW()
    
    # Foreign keys
    original_signal_id: Mapped[Optional[int]] = BIGINT_FK("signals.id", ondelete="SET NULL")
    
    # Relationships
    original_signal: Mapped[Optional[Signal]] = relationship(
        back_populates="replies", 
        uselist=False,
        lazy="selectin",
    )
    
    message: Mapped[Optional[Message]] = relationship(
        back_populates="signal_reply", 
        uselist=False,
        lazy="selectin",
    )
    
    mt5_trades: Mapped[List[Mt5Trade]] = relationship(
        back_populates="signal_replies",
        secondary="mt5_trade_signal_reply_link",
        lazy="selectin",
    )
    
    logs: Mapped[List[Log]] = relationship(
        back_populates="signal_reply",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="select",
    )
    
    def __repr__(self) -> str:
        return f"SignalReply(id={self.id!r}, action={self.action!r}, by={self.generated_by!r})"


class Message(Base):
    __tablename__ = "messages"
    
    # Primary key
    id: Mapped[int] = BIGINT_PK()
    
    # Core fields
    tg_msg_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    post_datetime: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = DATETIME_NOW()
    updated_at: Mapped[datetime] = DATETIME_AUTO_UPDATE()
    
    # Foreign keys
    tg_chat_id: Mapped[int] = BIGINT_FK("tg_chats.id", nullable=False, ondelete="CASCADE")
    signal_id: Mapped[Optional[int]] = BIGINT_FK("signals.id", ondelete="SET NULL")
    signal_reply_id: Mapped[Optional[int]] = BIGINT_FK("signal_replies.id", ondelete="SET NULL")
    
    # Relationships
    tg_chat: Mapped[TgChat] = relationship(
        back_populates="messages", 
        uselist=False,
        lazy="selectin",
    )
    
    signal: Mapped[Optional[Signal]] = relationship(
        back_populates="message", 
        uselist=False,
        lazy="selectin",
    )
    
    signal_reply: Mapped[Optional[SignalReply]] = relationship(
        back_populates="message", 
        uselist=False,
        lazy="selectin",
    )
    
    logs: Mapped[List[Log]] = relationship(
        back_populates="message",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="select",
    )
    
    __table_args__ = (
        Index("idx_messages_tgchatid_msgid", "tg_chat_id", "tg_msg_id"),
        UniqueConstraint("tg_chat_id", "tg_msg_id", name="uq_message_chat_msg"),
    )
    
    def __repr__(self) -> str:
        return f"Message(id={self.id!r}, tg_chat_id={self.tg_chat_id!r}, tg_msg_id={self.tg_msg_id!r})"


class CopySetupConfig(Base):
    __tablename__ = "copy_setup_configs"
    
    # Primary key
    id: Mapped[int] = BIGINT_PK()
    
    # Core fields
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="custom config")
    allowed_symbols: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    symbol_synonyms_mapping: Mapped[Dict[str, Any]] = JSONB_DICT()
    
    # Lot configuration
    lot_mode: Mapped[LotMode] = mapped_column(
        PgEnum(LotMode, name="lot_mode"), 
        nullable=False, 
        default=LotMode.AUTO
    )
    fixed_lot: Mapped[Optional[Decimal]] = DECIMAL_PRICE_OPTIONAL()
    max_risk_perc_from_equity_per_signal: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), 
        nullable=False, 
        default=Decimal('0')
    )
    
    # Multiple TP/Entry modes
    multiple_tp_mode: Mapped[MultipleTPMode] = mapped_column(
        PgEnum(MultipleTPMode, name="multiple_tp_mode"),
        nullable=False,
        default=MultipleTPMode.ALL
    )
    multiple_entry_mode: Mapped[MultipleEntryMode] = mapped_column(
        PgEnum(MultipleEntryMode, name="multiple_entry_mode"),
        nullable=False,
        default=MultipleEntryMode.ALL
    )
    
    # Behavior flags
    close_on_signal_reply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    modify_on_signal_reply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    close_on_msg_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ignore_invalid_prices: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    close_trades_before_everyday_swap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    close_trades_before_wednesday_swap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    close_trades_before_weekend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trailingstop_on_tps: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    follow_tp_and_sl_hits_from_others: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    
    # Limits and thresholds
    max_tp_prices: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_entry_prices: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    breakeven_on_tp_layer: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expire_at_tp_hit_before_entry: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expire_minutes_pending_trade: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expire_minutes_active_trade: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Percentages
    tradeprofit_percent_from_balans_for_breakeven: Mapped[Optional[Decimal]] = PERCENTAGE()
    
    # Foreign keys
    user_id: Mapped[int] = BIGINT_FK("users.id", nullable=False, ondelete="CASCADE")
    
    # Relationships
    user: Mapped[User] = relationship(
        back_populates="copy_setup_configs", 
        uselist=False,
        lazy="selectin",
    )
    
    copy_setups: Mapped[List[CopySetup]] = relationship(
        back_populates="config",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    
    def __repr__(self) -> str:
        return f"CopySetupConfig(id={self.id!r}, user_id={self.user_id!r}, name={self.name!r})"


class CopySetup(Base):
    __tablename__ = "copy_setups"
    
    # Primary key
    id: Mapped[int] = BIGINT_PK()
    
    # Core fields
    cs_token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    
    # Foreign keys
    user_id: Mapped[int] = BIGINT_FK("users.id", nullable=False, ondelete="CASCADE")
    config_id: Mapped[int] = BIGINT_FK("copy_setup_configs.id", nullable=False, ondelete="CASCADE")
    
    # Relationships
    user: Mapped[User] = relationship(
        back_populates="copy_setups", 
        uselist=False,
        lazy="selectin",
    )
    
    config: Mapped[CopySetupConfig] = relationship(
        back_populates="copy_setups", 
        uselist=False,
        lazy="selectin",
    )
    
    tg_chats: Mapped[List[TgChat]] = relationship(
        back_populates="copy_setups",
        secondary="copy_setup_tg_chat_link",
        lazy="selectin",
    )
    
    mt5_trades: Mapped[List[Mt5Trade]] = relationship(
        back_populates="copy_setup",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="selectin",
    )
    
    logs: Mapped[List[Log]] = relationship(
        back_populates="copy_setup",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="select",
    )
    
    def __repr__(self) -> str:
        return f"CopySetup(id={self.id!r}, user_id={self.user_id!r}, active={self.active!r})"


class Mt5Trade(Base):
    __tablename__ = "mt5_trades"
    
    # Primary key
    id: Mapped[int] = BIGINT_PK()
    
    # Core trade data
    ticket: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    type: Mapped[OrderType] = mapped_column(PgEnum(OrderType, name="mt5_order_type"), nullable=False)
    state: Mapped[Mt5TradeState] = mapped_column(PgEnum(Mt5TradeState, name="mt5_trade_state"), nullable=False)
    
    # Price data
    entry_price: Mapped[Decimal] = DECIMAL_PRICE()
    sl_price: Mapped[Decimal] = DECIMAL_PRICE()
    tp_price: Mapped[Decimal] = DECIMAL_PRICE()
    open_price: Mapped[Optional[Decimal]] = DECIMAL_PRICE_OPTIONAL()
    close_price: Mapped[Optional[Decimal]] = DECIMAL_PRICE_OPTIONAL()
    modified_sl: Mapped[Optional[Decimal]] = DECIMAL_PRICE_OPTIONAL()
    
    # Financial data
    volume: Mapped[Optional[Decimal]] = DECIMAL_PRICE_OPTIONAL()
    pnl: Mapped[Optional[Decimal]] = DECIMAL_PRICE_OPTIONAL()
    swap: Mapped[Optional[Decimal]] = DECIMAL_PRICE_OPTIONAL()
    commission: Mapped[Optional[Decimal]] = DECIMAL_PRICE_OPTIONAL()
    fee: Mapped[Optional[Decimal]] = DECIMAL_PRICE_OPTIONAL()
    
    # Signal tracking
    signal_post_datetime: Mapped[datetime] = mapped_column(nullable=False)
    signal_tps_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_entries_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Status tracking
    close_reason: Mapped[Optional[Mt5TradeCloseReason]] = mapped_column(
        PgEnum(Mt5TradeCloseReason, name="mt5_trade_close_reason"), 
        nullable=True
    )
    expire_reason: Mapped[Optional[Mt5TradeExpireReason]] = mapped_column(
        PgEnum(Mt5TradeExpireReason, name="mt5_trade_expire_reason"), 
        nullable=True
    )
    
    # Timestamps
    open_datetime: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    close_datetime: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = DATETIME_NOW()
    updated_at: Mapped[datetime] = DATETIME_AUTO_UPDATE()
    
    # Foreign keys
    signal_id: Mapped[Optional[int]] = BIGINT_FK("signals.id", ondelete="SET NULL")
    copy_setup_id: Mapped[Optional[int]] = BIGINT_FK("copy_setups.id", ondelete="CASCADE")
    
    # Relationships
    signal: Mapped[Optional[Signal]] = relationship(
        back_populates="mt5_trades", 
        uselist=False,
        lazy="selectin",
    )
    
    copy_setup: Mapped[Optional[CopySetup]] = relationship(
        back_populates="mt5_trades", 
        uselist=False,
        lazy="selectin",
    )
    
    signal_replies: Mapped[List[SignalReply]] = relationship(
        back_populates="mt5_trades",
        secondary="mt5_trade_signal_reply_link",
        lazy="selectin",
    )
    
    logs: Mapped[List[Log]] = relationship(
        back_populates="mt5_trade",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="select",
    )
    
    __table_args__ = (
        Index("idx_mt5trade_symbol_ticket", "symbol", "ticket"),
        Index("idx_mt5trade_state", "state"),
        Index("idx_mt5trade_created_at", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"Mt5Trade(id={self.id!r}, ticket={self.ticket!r}, symbol={self.symbol!r}, state={self.state!r})"


class Log(Base):
    __tablename__ = "logs"
    
    # Primary key
    id: Mapped[int] = BIGINT_PK()
    
    # Core fields
    created_at: Mapped[datetime] = DATETIME_NOW()
    context: Mapped[Dict[str, Any]] = JSONB_DICT()
    
    # Foreign keys (all optional for flexible logging)
    user_id: Mapped[Optional[int]] = BIGINT_FK("users.id", ondelete="SET NULL")
    copy_setup_id: Mapped[Optional[int]] = BIGINT_FK("copy_setups.id", ondelete="SET NULL")
    signal_id: Mapped[Optional[int]] = BIGINT_FK("signals.id", ondelete="SET NULL")
    mt5_trade_id: Mapped[Optional[int]] = BIGINT_FK("mt5_trades.id", ondelete="SET NULL")
    message_id: Mapped[Optional[int]] = BIGINT_FK("messages.id", ondelete="SET NULL")
    signal_reply_id: Mapped[Optional[int]] = BIGINT_FK("signal_replies.id", ondelete="SET NULL")
    
    # Relationships
    user: Mapped[Optional[User]] = relationship(
        back_populates="logs", 
        uselist=False,
        lazy="selectin",
    )
    
    copy_setup: Mapped[Optional[CopySetup]] = relationship(
        back_populates="logs", 
        uselist=False,
        lazy="selectin",
    )
    
    signal: Mapped[Optional[Signal]] = relationship(
        back_populates="logs", 
        uselist=False,
        lazy="selectin",
    )
    
    mt5_trade: Mapped[Optional[Mt5Trade]] = relationship(
        back_populates="logs", 
        uselist=False,
        lazy="selectin",
    )
    
    message: Mapped[Optional[Message]] = relationship(
        back_populates="logs", 
        uselist=False,
        lazy="selectin",
    )
    
    signal_reply: Mapped[Optional[SignalReply]] = relationship(
        back_populates="logs", 
        uselist=False,
        lazy="selectin",
    )
    
    def __repr__(self) -> str:
        return f"Log(id={self.id!r}, created_at={self.created_at!r})"


# --- Association tables (many-to-many) ---

CopySetupTgChatLink = Table(
    "copy_setup_tg_chat_link",
    metadata,
    Column(
        "copy_setup_id",
        BigInteger,
        ForeignKey("copy_setups.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column(
        "tg_chat_id",
        BigInteger,
        ForeignKey("tg_chats.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
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
        nullable=False,
    ),
    Column(
        "signal_reply_id",
        BigInteger,
        ForeignKey("signal_replies.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    UniqueConstraint("mt5_trade_id", "signal_reply_id", name="uq_mt5_trade_signal_reply"),
    Index("ix_mt5_trade_signal_reply_trade_id", "mt5_trade_id"),
    Index("ix_mt5_trade_signal_reply_reply_id", "signal_reply_id"),
)


# Make all models available for import
__all__ = [
    "Base",
    "metadata",
    "User",
    "TgChat", 
    "Signal",
    "SignalReply",
    "Message",
    "CopySetupConfig",
    "CopySetup",
    "Mt5Trade",
    "Log",
    "CopySetupTgChatLink",
    "Mt5TradeSignalReplyLink",
]