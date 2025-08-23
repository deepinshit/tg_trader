import secrets
from fastapi import Request, HTTPException, status

def generate_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token

def validate_csrf(request: Request, token: str):
    expected = request.session.get("csrf_token")
    if not expected or expected != token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )
