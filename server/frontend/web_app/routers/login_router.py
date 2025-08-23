from fastapi import APIRouter, Request, Form, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse

from frontend.web_app.utils import templates
from auth.csrf import generate_csrf_token, validate_csrf
from auth.hashing import verify_password
from backend.db.crud.user import get_user_on_username
from backend.db.functions import get_session, AsyncSession

router = APIRouter(include_in_schema=False)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "csrf_token": csrf_token},
    )


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: AsyncSession = Depends(get_session),
):
    try:
        validate_csrf(request, csrf_token)
    except ValueError:
        return HTMLResponse("Invalid CSRF", status_code=status.HTTP_400_BAD_REQUEST)

    user = await get_user_on_username(username, db)  # <- you already have this
    if not user or not verify_password(password, user.hashed_password):
        # re-render with error and a fresh token
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "csrf_token": generate_csrf_token(request), "error": "Invalid credentials"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # minimal session: only store the user_id
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
