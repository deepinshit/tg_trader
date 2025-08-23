from fastapi import Depends, Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from backend.db.functions import get_session
from models import User

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> User:
    """
    Retrieve currently logged-in user from session cookie.
    Ensures the user exists in DB.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user
