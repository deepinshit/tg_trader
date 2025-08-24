# api/app.py
import logging
import secrets
import uuid
from decimal import Decimal
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Request, status
from sqlalchemy import inspect

from api.schemes import (
    ClientInitBody,
    ClientInitResponse,
    PollBody,
    PollResponse,
    Session,
    SignalReply,
    Trade,
)
from backend.redis.store import RedisStore
from backend.redis.functions import get_redis_store
from auth.auth import authenticate
from models import CopySetupConfig
from backend.db.functions import get_session, AsyncSession
from backend.db.crud.copy_setup import get_copy_setup_on_token

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI()
SESSION_TTL: int = 3600  # 1 hour TTL


# ---------------------------
# Helper to serialize config
# ---------------------------
def serialize_copysetup_config(config: CopySetupConfig) -> Dict[str, Any]:
    """Convert SQLAlchemy CopySetup.config to plain dict compatible with Pydantic."""
    result: Dict[str, Any] = {}
    if config is None:
        return result

    for attr in config.__mapper__.attrs:
        value = getattr(config, attr.key)
        if value is None:
            result[attr.key] = None
        elif hasattr(value, "name"):  # Enum
            result[attr.key] = str(value)
        elif isinstance(value, Decimal):
            result[attr.key] = float(value)
        elif isinstance(value, list):
            result[attr.key] = [
                str(v) if hasattr(v, "name") else v for v in value
            ]
        else:
            result[attr.key] = value
    return result


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response


# ---------------------------
# CLIENT INIT
# ---------------------------
@app.post("/client/init", response_model=ClientInitResponse, status_code=status.HTTP_201_CREATED)
async def client_init(
    body: ClientInitBody,
    request: Request,
    auth: Dict[str, Optional[str]] = Depends(authenticate),
    redis: RedisStore = Depends(get_redis_store),
    db_ses: AsyncSession = Depends(get_session),
) -> ClientInitResponse:
    """Initialize a client session"""

    if not auth or not auth.get("copy_setup_token"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="X-CopySetup-Token header missing")

    # Fetch CopySetup from DB
    async with db_ses.begin():
        copy_setup = await get_copy_setup_on_token(db_ses, auth["copy_setup_token"])
        if copy_setup is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid copy_setup_token")
        config = copy_setup.config
        config_dict = {attr.key: getattr(config, attr.key) for attr in inspect(config).mapper.column_attrs}

    # Generate refresh token and client instance
    refresh_token = secrets.token_urlsafe(16)
    client_instance_id = body.client_instance_id or f"cid-{uuid.uuid4()}"
    ip = request.client.host if request.client else "0.0.0.0"

    session_data = Session.model_validate({
        "refresh_token": refresh_token,
        "copy_setup_id": copy_setup.id,
        "client_instance_id": client_instance_id,
        "ip": ip,
        "poll_interval": body.poll_interval,
    })

    await redis.add_session(session_data.model_dump(mode="json", exclude_unset=True), ttl=SESSION_TTL)
    logger.info("Initialized session for client_instance_id=%s", client_instance_id)

    response_data = {
        "client_instance_id": client_instance_id,
        "refresh_token": refresh_token,
        "expire_sec": SESSION_TTL,
        "server_caps": {},
        "lot_mode": config_dict.get("lot_mode", "default"),
    }

    return ClientInitResponse.model_validate(response_data)


# ---------------------------
# POLL ENDPOINT
# ---------------------------
@app.post("/poll", response_model=PollResponse)
async def poll(
    body: PollBody,
    auth: Dict[str, Optional[str]] = Depends(authenticate),
    redis: RedisStore = Depends(get_redis_store),
) -> PollResponse:
    """Poll endpoint: validate session, return pending trades and signal replies"""

    session: Optional[Session] = await redis.get_session(auth["refresh_token"])
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invalid/expired refresh_token")

    # Generate a new refresh token for each poll
    refresh_token = secrets.token_urlsafe(16)
    session.refresh_token = refresh_token
    await redis.add_session(session.model_dump(mode="json"), ttl=SESSION_TTL)

    client_trades: List[Trade] = [Trade.model_validate(t) for t in body.trades]

    logger.info(
        "Polling client_instance_id=%s, trades received=%d",
        body.client_instance_id,
        len(client_trades)
    )

    pending_trades: List[Trade] = [
        Trade.model_validate(r)
        for r in await redis.get_pending_trades(body.client_instance_id, limit=100)
    ]
    pending_signal_replies: List[SignalReply] = [
        SignalReply.model_validate(r)
        for r in await redis.get_pending_signal_replies(body.client_instance_id, limit=100)
    ]

    response = {
        "refresh_token": refresh_token,
        "trades": pending_trades,
        "signal_replies": pending_signal_replies,
    }

    return PollResponse.model_validate(response)
