from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from models import User
from standard_db_models import ADMIN
from backend.db.functions import get_session_context, AsyncSession

async def get_or_create_admin() -> User:
    """
    Ensure an admin user exists.
    - Returns existing admin if found.
    - Otherwise inserts a new one.
    """
    async with get_session_context() as session:
        # 1. Check if admin already exists
        stmt = select(User).where(User.email == ADMIN.email)
        result = await session.execute(stmt)
        admin = result.scalar_one_or_none()

        if admin:
            return admin

        # 2. Create admin if not found
        new_admin = ADMIN
        session.add(new_admin)

        try:
            await session.commit()
        except IntegrityError:
            # Race condition: someone else inserted admin between check & commit
            await session.rollback()
            result = await session.execute(stmt)
            new_admin = result.scalar_one()
        
        return new_admin

async def get_user_on_username(username: str, session: AsyncSession) -> Optional[User]:
    stmnt = select(User).where(User.username == username)
    result = await session.execute(stmnt)
    return result.scalar_one_or_none()