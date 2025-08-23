from typing import List, Dict, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from frontend.web_app.utils import templates, get_current_user, inject_common_context
from backend.db.functions import get_session, AsyncSession
from backend.db.crud.general import read
from models import User, TgChat


async def get_tg_chat_detail(user_id: int, chat_id: int, db: AsyncSession) -> Dict[str, Any]:
    """
    TODO implement:
    {
      "chat": {"id": int, "title": str, "username": str|None},
      "signals": [
        {"id": int, "symbol": str, "type": str, "tps_hit": dict, "entries_hit": dict, "created_at": str}
      ],
      "stats": { "total_signals": int, "last_signal_at": str|None }
    }
    """
    return {"chat": None, "signals": [], "stats": {}}
# -----------------------------------------------------------------------------

router = APIRouter(include_in_schema=False)


@router.get("/tg_chats", response_class=HTMLResponse)
async def tg_chats_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    chats = await read(TgChat, db)
    ctx = {
        **inject_common_context(request, user),
        "chats": chats,
    }
    return templates.TemplateResponse("tg_chats.html", ctx)


@router.get("/tg_chat/{chat_id}", response_class=HTMLResponse)
async def tg_chat_detail_page(
    chat_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    data = await get_tg_chat_detail(user.id, chat_id, db)
    if not data.get("chat"):
        return HTMLResponse("Not found", status_code=404)
    ctx = {
        **inject_common_context(request, user),
        "data": data,
    }
    return templates.TemplateResponse("tg_chat_detail.html", ctx)
