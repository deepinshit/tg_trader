# api/app.py
import logging
import secrets
import uuid
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Request, status

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
from models import CopySetup
from backend.db.functions import get_session, AsyncSession
from backend.db.crud.copy_setup import get_copy_setup_on_token

# -------------------------------------------------------------------
# App Setup
# -------------------------------------------------------------------

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI()
SESSION_TTL: int = 3600  # Session expiration (1h)

# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@app.post("/client/init", response_model=ClientInitResponse, status_code=status.HTTP_201_CREATED)
async def client_init(
    body: ClientInitBody,
    request: Request,
    auth: Dict[str, Optional[str]] = Depends(authenticate),
    redis: RedisStore = Depends(get_redis_store),
    db_ses: AsyncSession = Depends(get_session)
) -> ClientInitResponse:
    """
    Initialize a client session:
    - Validates CopySetup token
    - Generates/reuses refresh_token
    - Stores session metadata in Redis
    - Returns client initialization response
    """
    copy_setup = await get_copy_setup_on_token(db_ses, auth["copy_setup_token"])
    if copy_setup is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid copy_setup_token")

    refresh_token = secrets.token_urlsafe(16)
    client_instance_id = body.client_instance_id or f"cid-{uuid.uuid4()}"
    ip = request.client.host if request.client else "0.0.0.0"

    session: Optional[Session] = await redis.get_session_by_client(client_instance_id)

    # Hydrate Session model directly from dict
    session = Session.model_validate({
        "refresh_token": refresh_token,
        "copy_setup_id": copy_setup.id,
        "client_instance_id": client_instance_id,
        "ip": ip,
        "poll_interval": body.poll_interval,
    })

    # Store in Redis as clean JSON
    await redis.add_session(
        session.model_dump(mode="json", exclude_unset=True),
        ttl=SESSION_TTL,
    )

    logger.info("Initialized session for client_instance_id=%s", client_instance_id)

    # Hydrate response model in one go
    return ClientInitResponse.model_validate({
        "client_instance_id": client_instance_id,
        "refresh_token": refresh_token,
        "expire_sec": SESSION_TTL,
        "server_caps": {},  # Future features
        "lot_mode": copy_setup.config.lot_mode if copy_setup.config else "default",
        **(copy_setup.config.to_dict() if copy_setup.config else {}),
    })


@app.post("/poll", response_model=PollResponse)
async def poll(
    body: PollBody,
    auth: Dict[str, Optional[str]] = Depends(authenticate),
    redis: RedisStore = Depends(get_redis_store),
) -> PollResponse:
    """
    Poll endpoint:
    - Validates active session in Redis
    - Checks refresh_token consistency
    - Returns trades + pending signal replies
    """
    session: Optional[Session] = await redis.get_session(auth["refresh_token"])
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Invalid/expired refresh_token")
    
    refresh_token = secrets.token_urlsafe(16)

    # Stub: Persist trades if needed
    client_trades: List[Trade] = [
        Trade.model_validate(t) for t in body.trades
    ]

    logger.debug(
        "Polled client_instance_id=%s → trades=%d",
        body.client_instance_id,
        len(client_trades),
        extra={"copy_setup_id": session.copy_setup_id}
    )

    pending_trades: List[Trade] = [
        Trade.model_validate(r)
        for r in await redis.get_pending_trades(body.client_instance_id, limit=100)
    ]

    # Get signal replies (Redis returns dicts → validate in bulk)
    pending_signal_replies: List[SignalReply] = [
        SignalReply.model_validate(r)
        for r in await redis.get_pending_signal_replies(body.client_instance_id, limit=100)
    ]

    return PollResponse.model_validate({
        "refresh_token": refresh_token,
        "trades": pending_trades,
        "signal_replies": pending_signal_replies,
    })
