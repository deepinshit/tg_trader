import secrets
import logging
from fastapi import FastAPI, Request, status
from fastapi.responses import RedirectResponse
from fastapi.exceptions import HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .routers import dashboard_router
from .routers import login_router
from .routers import copy_setups_router
from .routers import tg_chats_router
from cfg import PRODUCTION
from .utils import templates

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# app setup
# ----------------------------------------------------------------------------
app = FastAPI()

# Session secret (must be strong & persistent in production!)
SESSION_SECRET = secrets.token_hex(32)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,  # rotate in prod
    session_cookie="session",
    same_site="strict" if PRODUCTION else "lax",
    https_only=PRODUCTION,   # only over HTTPS if prod
    max_age=60 * 60 * 1,     # 1h session
)

app.mount("/static", StaticFiles(directory="frontend/templates/static"), name="static")

app.include_router(login_router)
app.include_router(dashboard_router)
app.include_router(copy_setups_router)
app.include_router(tg_chats_router)


# ---- Handle 401 Unauthorized (redirect to login) ----
@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc: HTTPException):
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


# ---- Handle 404 Not Found ----
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        "errors/404.html",
        {"request": request},
        status_code=status.HTTP_404_NOT_FOUND,
    )


# ---- Handle 500 Internal Server Error ----
@app.exception_handler(500)
async def server_error_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        "errors/500.html",
        {"request": request},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
