

from models import User
from enums import UserRole
from auth.hashing import hash_password
from cfg import ADMIN_PW

ADMIN = User(
    username="admin", 
    email="admin@tg_trader.com", 
    hashed_password=hash_password(ADMIN_PW),
    role=UserRole.ADMIN
) 
