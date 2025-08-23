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
    PENDING_ORDER = "PENDING_ORDER"
    ACTIVE_POSITION = "ACTIVE_POSITION"
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
    SUPER_GROUP = "SUPER_GROUP"


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    FREE_USER = "FREE_USER"
    VIP_1_USER = "VIP_1_USER"