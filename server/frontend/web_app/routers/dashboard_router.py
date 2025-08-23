from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from frontend.web_app.utils import templates, get_current_user, inject_common_context
from models import User
from backend.db.functions import get_session, AsyncSession

# ---- TODOs: you implement these and keep the signatures. ----
# return quick stats for the dashboard
async def get_dashboard_stats(user_id: int, db: AsyncSession) -> dict:
    """
    TODO implement: return {
        "active_copy_setups": int,
        "total_configs": int,
        "top_chats": List[{"id": int, "title": str, "signals_last_24h": int}],
        "recent_activity": List[str]  # optional
    }
    """
    return {
        "active_copy_setups": 0,
        "total_configs": 0,
        "top_chats": [],
        "recent_activity": [],
    }
# --------------------------------------------------------------

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):  
    stats = await get_dashboard_stats(user.id, db)
    ctx = {
        **inject_common_context(request, user),
        "stats": stats,
    }
    return templates.TemplateResponse("dashboard.html", ctx)
