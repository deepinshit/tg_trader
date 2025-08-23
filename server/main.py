import logging
import asyncio
from contextlib import asynccontextmanager
import sys
import time
from typing import Any

from fastapi import FastAPI
from uvicorn import Server, Config

from backend.db.functions import setup_db, dispose_engine as close_db
from frontend.web_app.app import app as frontend_app
from api.app import app as api_app
from backend.messages.tg.client import init_telegram_client
from backend.messages.tg.handlers import register_handlers
from background_tasks import shutdown_background_tasks
from backend.db.crud.user import get_or_create_admin
from backend.messages.tg.functions import update_dialogs


class ExtraFormatter(logging.Formatter):
    # Use UTC for timestamps
    converter = time.gmtime  

    def format(self, record: logging.LogRecord) -> str:
        s = super().format(record)

        # baseline standard attributes
        standard_attrs = set(logging.makeLogRecord({}).__dict__.keys())

        # also exclude computed fields that appear after formatting
        ignore = standard_attrs | {"message", "asctime"}

        # collect only true extras
        extras = {k: v for k, v in record.__dict__.items() if k not in ignore}

        if extras:
            formatted_extras = ", ".join(f"{k}={v}" for k, v in extras.items())
            s += f" | extra: ({formatted_extras})"
        return s



# --- Logging Configuration ---

# === Custom formatter ===
formatter = ExtraFormatter(
    '[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d in %(funcName)s()] - %(message)s'
)

# === Handler for stderr (WARNING and above only) ===
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.WARNING)
stderr_handler.setFormatter(formatter)

class MaxLevelFilter(logging.Filter):
    def __init__(self, max_level):
        self.max_level = max_level
    
    def filter(self, record):
        return record.levelno <= self.max_level

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.addFilter(MaxLevelFilter(logging.INFO))
stdout_handler.setLevel(logging.DEBUG)
stdout_handler.setFormatter(formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)  # Capture everything
root_logger.handlers.clear()
root_logger.addHandler(stdout_handler)
root_logger.addHandler(stderr_handler)

# === Silence 3rd-party INFO/DEBUG logs fully ===
noisy_loggers = [
    "python_multipart.multipart",
    "aiosqlite",
    "sqlalchemy",
    "sqlalchemy.engine",
    "httpx",
    "telethon",
    "telethon.network",
    "telethon.network.mtprotosender",
    "openai",
    "openai._base_client",
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "sqlalchemy.engine.Engine",
    "sqlalchemy.pool"
]

for name in noisy_loggers:
    logger = logging.getLogger(name)

    # 🔥 Remove all existing handlers
    while logger.handlers:
        handler = logger.handlers.pop()
        logger.removeHandler(handler)

    # 🔒 Only allow WARNING and above
    logger.setLevel(logging.WARNING)

    # 👂 Let messages propagate to your root logger
    logger.propagate = True

# === Your own logger (optional: allow more detailed logging if desired) ===
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # You can log debug/info from your code if needed

logger.debug("test")
logger.info("test")
logger.warning("test")
logger.error("test")
logger.critical("test")
# --------------------------------


# Root app with lifespan
app = FastAPI()
app.mount("/api", api_app)
app.mount("/", frontend_app)

async def run_app(app: FastAPI, host: str = "127.0.0.1", port: int = 8000, log_config: Any = None, log_level: int = logging.INFO, **kwargs):
    config = Config(app, host, port, log_config=log_config, log_level=log_level, **kwargs)
    server = Server(config)
    return await server.serve()


async def main():
    client = None
    try:
        async with asyncio.TaskGroup() as tg:
            # Database setup
            db_setup_task = tg.create_task(setup_db())

            # Telegram client setup
            async def init_client_and_handlers():
                nonlocal client
                client = await init_telegram_client()
                register_handlers(client)
                logger.info(
                    "Telegram client initialized and handlers registered.",
                    extra={"component": "telegram"},
                )

            tg_setup_task = tg.create_task(init_client_and_handlers())

            await db_setup_task
            tg.create_task(get_or_create_admin())

            await tg_setup_task
            tg.create_task(update_dialogs(client=client, limit=None))

            tg.create_task(run_app(app))

        logger.info("Application startup completed successfully.")

    except Exception as e:
        logger.exception(
            "Application startup failure.",
            extra={"error_type": type(e).__name__},
        )
        raise

    finally:
        logger.info("Application shutdown initiated.")
        try:
            await shutdown_background_tasks()
            if client:
                await client.disconnect()
                logger.info(
                    "Telegram client disconnected.",
                    extra={"component": "telegram"},
                )
            # Example: close DB connections here
            await close_db()
        except Exception as e:
            logger.exception(
                "Error during shutdown cleanup.",
                extra={"error_type": type(e).__name__},
            )
        logger.info("Application shutdown completed.")

if __name__ == "__main__":
    asyncio.run(main())