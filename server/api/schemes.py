# api/schemes.py
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# -------------------------------------------------------------------
# Core Domain Models
# -------------------------------------------------------------------

class Trade(BaseModel):
    """
    Represents a trade lifecycle event or state from the client.
    Typically synced from the trading platform (e.g., MT4/MT5).
    """
    id: Optional[int] = None
    signal_id: int

    # Platform trade identifiers
    ticket: Optional[int] = None
    symbol: Optional[str] = None
    type: Optional[str] = None

    # Price levels
    entry_price: Optional[float] = None
    open_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    modified_sl: Optional[float] = None
    close_price: Optional[float] = None
    current_price: Optional[float] = None

    # Timing
    open_datetime: Optional[datetime] = None
    close_datetime: Optional[datetime] = None
    signal_post_datetime: Optional[datetime] = None  # Always UTC

    # State / control
    state: str
    signal_tps_idx: Optional[int] = None
    signal_entries_idx: Optional[int] = None
    close_reason: Optional[str] = None
    expire_reason: Optional[str] = None

    # Financials
    volume: Optional[float] = None
    pnl: Optional[float] = None
    swap: Optional[float] = None
    commission: Optional[float] = None
    fee: Optional[float] = None
    comment: Optional[str] = None
    magic: Optional[int] = None

    class Config:
        extra = "forbid"
        from_attributes = True


class SignalReply(BaseModel):
    """
    Represents a server reply to a signal,
    used to inform client of actions taken or errors.
    """
    id: int
    action: str
    generated_by: str
    original_signal_id: int
    info_message: Optional[str] = None

    class Config:
        extra = "forbid"


class Session(BaseModel):
    """
    Session metadata stored in Redis to track active clients.
    """
    refresh_token: str
    copy_setup_id: int
    client_instance_id: str
    ip: str
    poll_interval: int

    class Config:
        extra = "forbid"


# -------------------------------------------------------------------
# API Request / Response Models
# -------------------------------------------------------------------

class ClientInitBody(BaseModel):
    """Request payload for /client/init."""
    account_id: int
    account_name: str
    account_server: str
    account_balance: float
    account_equity: float
    account_open_pnl: float
    poll_interval: int
    client_version: float
    client_instance_id: Optional[str] = None

    class Config:
        extra = "forbid"


class ClientInitResponse(BaseModel):
    """Response returned by /client/init."""
    client_instance_id: str
    refresh_token: str
    expire_sec: int

    # Server-defined capabilities
    server_caps: Dict[str, Any] = Field(default_factory=dict)
    lot_mode: str

    # Optional risk/trade controls
    fixed_lot: Optional[float] = None
    breakeven_on_tp_layer: Optional[int] = None
    close_trades_before_everyday_swap: bool = False
    close_trades_before_wednesday_swap: bool = False
    close_trades_before_weekend: bool = False
    trailingstop_on_tps: bool = False
    tradeprofit_percent_from_balans_for_breakeven: Optional[float] = None
    expire_minutes_pending_trade: Optional[int] = None
    expire_minutes_active_trade: Optional[int] = None
    expire_at_tp_hit_before_entry: Optional[int] = None

    class Config:
        extra = "forbid"


class PollBody(BaseModel):
    """Request payload for /poll."""
    account_id: int
    client_instance_id: str
    account_balance: float
    account_equity: float
    trades: List[Trade] = Field(default_factory=list)
    trade_ack_ids: List[int] = Field(default_factory=list)
    signal_reply_ack_ids: List[int] = Field(default_factory=list)

    class Config:
        extra = "forbid"


class PollResponse(BaseModel):
    """Response returned by /poll."""
    refresh_token: str
    trades: List[Trade] = Field(default_factory=list)
    signal_replies: List[SignalReply] = Field(default_factory=list)

    class Config:
        extra = "forbid"
