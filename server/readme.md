# enums.py

from enum import Enum

class OrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SignalReplyAction(str, Enum):
    BREAKEVEN = "BREAKEVEN"
    CLOSE = "CLOSE"
    MODIFY = "MODIFY"


class SignalReplyGeneratedBy(str, Enum):
    REPLY = "REPLY"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    AI = "AI"


class Mt5TradeState(str, Enum):
    PENDING_QUEUE = "PENDING_QUEUE"
    PENDING = "PENDING_ORDER"
    ACTIVE = "ACTIVE_POSITION"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class Mt5TradeCloseReason(str, Enum):
    ACTIVE_TIME_EXPIRE = "ACTIVE_TIME_EXPIRE"
    SL_HIT = "SL_HIT"
    TP_HIT = "TP_HIT"
    MANUAL_CLOSE = "MANUAL_CLOSE"
    SIGNAL_REPLY = "SIGNAL_REPLY"


class Mt5TradeExpireReason(str, Enum):
    MANUAL_CANCEL = "MANUAL_CANCEL"
    PENDING_TIME_EXPIRE = "PENDING_TIME_EXPIRE"
    SL_HIT = "SL_HIT"
    TP_HIT = "TP_HIT"
    SIGNAL_REPLY = "SIGNAL_REPLY"
    SYMBOL_DISABLED = "SYMBOL_DISABLED"
    FAILED_EXECUTION = "FAILED_EXECUTION"

class LotMode(str, Enum):
    AUTO = "AUTO"
    FIXED = "FIXED"


class MultipleTPMode(str, Enum):
    ALL = "ALL"
    FIRST_LAYER = "FIRST_LAYER"
    LAST_LAYER = "LAST_LAYER"
    AVERAGE = "AVERAGE"


class MultipleEntryMode(str, Enum):
    ALL = "ALL"
    FIRST_LAYER = "FIRST_LAYER"
    LAST_LAYER = "LAST_LAYER"
    AVERAGE = "AVERAGE"

class TgChatType(str, Enum):
    PRIVATE = "PRIVATE"
    CHANNEL = "CHANNEL"
    GROUP = "GROUP"
    UNKNOWN = "UNKNOWN"

# .models.py

from typing import Optional, List
from datetime import datetime

from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, DOUBLE_PRECISION

from helpers import utc_now
from model_links import CopySetupTgChatLink, Mt5TradeSignalReplyLink

# --------------------
# MAIN TABLES
# --------------------

class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utc_now)
    email: str = Field(unique=True, index=True)
    hashed_password: str

    copy_setups: List["CopySetup"] = Relationship(back_populates="user")
    copy_setup_configs: List["CopySetupConfig"] = Relationship(back_populates="user")
    logs: List["Log"] = Relationship(back_populates="user")


class TgChat(SQLModel, table=True):
    __tablename__ = "tg_chats"

    id: int = Field(primary_key=True)
    title: str
    username: str
    chat_type: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    messages: List["Message"] = Relationship(back_populates="tg_chat")
    copy_setups: List["CopySetup"] = Relationship(
        back_populates="tg_chats",
        link_model=CopySetupTgChatLink
    )


class Signal(SQLModel, table=True):
    __tablename__ = "signals"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str
    type: str
    entry_prices: List[float] = Field(sa_column=Column(ARRAY(DOUBLE_PRECISION)))
    tp_prices: List[float] = Field(sa_column=Column(ARRAY(DOUBLE_PRECISION)))
    sl_price: float
    max_tp_hit: Optional[int]
    sl_hit: Optional[datetime]
    tps_hit: dict = Field(sa_column=Column(JSONB))
    entrys_hit: dict = Field(sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    message: "Message" = Relationship(back_populates="signal")
    replies: List["SignalReply"] = Relationship(back_populates="original_signal")
    mt5_trades: List["Mt5Trade"] = Relationship(back_populates="signal")
    logs: List["Log"] = Relationship(back_populates="signal")


class SignalReply(SQLModel, table=True):
    __tablename__ = "signal_replies"

    id: Optional[int] = Field(default=None, primary_key=True)
    action: str
    generated_by: Optional[str]
    info_message: Optional[str]
    original_signal_id: Optional[int] = Field(foreign_key="signals.id")
    created_at: datetime = Field(default_factory=utc_now)

    original_signal: Optional[Signal] = Relationship(back_populates="replies")
    message: "Message" = Relationship(back_populates="signal_reply")
    mt5_trades: List["Mt5Trade"] = Relationship(
        back_populates="signal_replies", link_model=Mt5TradeSignalReplyLink
    )
    logs: List["Log"] = Relationship(back_populates="signal_reply")


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    tg_chat_id: int = Field(foreign_key="tg_chats.id")
    tg_msg_id: int
    text: str
    post_datetime: datetime
    signal_id: Optional[int] = Field(default=None, foreign_key="signals.id")
    signal_reply_id: Optional[int] = Field(default=None, foreign_key="signal_replies.id")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    tg_chat: TgChat = Relationship(back_populates="messages")
    signal: Optional[Signal] = Relationship(back_populates="message")
    signal_reply: Optional[SignalReply] = Relationship(back_populates="message")
    logs: List["Log"] = Relationship(back_populates="message")


class CopySetupConfig(SQLModel, table=True):
    __tablename__ = "copy_setup_configs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    allowed_symbols: Optional[str]
    symbol_synonyms_mapping: dict = Field(sa_column=Column(JSONB))
    close_on_signal_reply: bool = False
    modify_on_signal_reply: bool = False
    close_on_msg_delete: bool = False
    close_on_new_signal_same_symbol: bool = False
    lot_mode: Optional[str]
    fixed_lot: Optional[float]
    max_price_range_perc: Optional[float]
    ignore_prices_out_of_range: bool = True
    multiple_tp_mode: Optional[str]
    multiple_entry_mode: Optional[str]
    breakeven_on_tp_layer: Optional[int]
    close_trades_before_everyday_swap: bool = False
    close_trades_before_wednesday_swap: bool = False
    close_trades_before_weekend: bool = False
    trailingstop_on_tps: bool = False
    tradeprofit_percent_from_balans_for_breakeven: Optional[float]
    expire_minutes_pending_trade: Optional[int]
    expire_minutes_active_trade: Optional[int]
    expire_at_tp_hit_before_entry: Optional[int]
    follow_tp_and_sl_hits_from_others: bool = False
    keep_managing_when_not_active: bool = False

    user: User = Relationship(back_populates="copy_setup_configs")
    copy_setups: List["CopySetup"] = Relationship(back_populates="config")


class CopySetup(SQLModel, table=True):
    __tablename__ = "copy_setups"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    config_id: int = Field(foreign_key="copy_setup_configs.id")
    cs_token: Optional[str]
    active: bool = True

    user: User = Relationship(back_populates="copy_setups")
    config: CopySetupConfig = Relationship(back_populates="copy_setups")
    tg_chats: List[TgChat] = Relationship(
        back_populates="copy_setups", link_model=CopySetupTgChatLink
    )
    mt5_trades: List["Mt5Trade"] = Relationship(back_populates="copy_setup")
    logs: List["Log"] = Relationship(back_populates="copy_setup")


class Mt5Trade(SQLModel, table=True):
    __tablename__ = "mt5_trades"

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket: Optional[int]
    symbol: str
    type: str
    sl_price: float
    entry_price: float
    tp_price: float
    state: str
    signal_tps_idx: int 
    signal_entries_idx: int
    signal_post_datetime: datetime
    close_reason: Optional[str]
    expire_reason: Optional[str]
    modified_sl: Optional[float]
    open_price: Optional[float]
    open_datetime: Optional[datetime]
    volume: Optional[float]
    pnl: Optional[float]
    swap: Optional[float]
    commission: Optional[float]
    fee: Optional[float]
    close_price: Optional[float]
    close_datetime: Optional[datetime]
    signal_id: Optional[int] = Field(foreign_key="signals.id")
    copy_setup_id: Optional[int] = Field(foreign_key="copy_setups.id")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    signal: Optional[Signal] = Relationship(back_populates="mt5_trades")
    copy_setup: Optional[CopySetup] = Relationship(back_populates="mt5_trades")
    signal_replies: List[SignalReply] = Relationship(
        back_populates="mt5_trades", link_model=Mt5TradeSignalReplyLink
    )
    logs: List["Log"] = Relationship(back_populates="mt5_trade")


class Log(SQLModel, table=True):
    __tablename__ = "logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utc_now)
    context: dict = Field(sa_column=Column(JSONB))
    user_id: Optional[int] = Field(foreign_key="users.id")
    copy_setup_id: Optional[int] = Field(foreign_key="copy_setups.id")
    signal_id: Optional[int] = Field(foreign_key="signals.id")
    mt5_trade_id: Optional[int] = Field(foreign_key="mt5_trades.id")
    message_id: Optional[int] = Field(foreign_key="messages.id")
    signal_reply_id: Optional[int] = Field(foreign_key="signal_replies.id")

    user: Optional[User] = Relationship(back_populates="logs")
    copy_setup: Optional[CopySetup] = Relationship(back_populates="logs")
    signal: Optional[Signal] = Relationship(back_populates="logs")
    mt5_trade: Optional[Mt5Trade] = Relationship(back_populates="logs")
    message: Optional[Message] = Relationship(back_populates="logs")
    signal_reply: Optional[SignalReply] = Relationship(back_populates="logs")

