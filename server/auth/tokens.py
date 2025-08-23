import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, status

from helpers import utc_now

SECRET_KEY = "super-secret-key"  # 🔒 set via env var in production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def create_access_token(subject: str) -> str:
    expire = utc_now(True) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

import secrets

def generate_cs_token(length: int = 32) -> str:
    """Generate a secure random token for CopySetup"""
    return secrets.token_urlsafe(length)
