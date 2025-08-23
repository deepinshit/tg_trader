from typing import Optional

from fastapi import Request, Depends, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.functions import get_session
from models import User

templates = Jinja2Templates(directory="frontend/templates")

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> User:
    """
    Must return models.User or raise HTTPException(401).
    Reads `user_id` from the session and verifies it exists.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user = await db.get(User, user_id)
    if not user:
        request.session.clear()
        
    return user

def inject_common_context(request: Request, user: Optional[User]) -> dict:
    """Small helper to keep templates DRY."""
    return {
        "request": request,
        "current_user": user,
    }
