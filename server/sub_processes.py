import asyncio
import aiohttp
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

NGROK_PATH = r"C:\ngrok-v3-stable-windows-amd64\ngrok.exe"#Path(r"C:\ngrok-v3-stable-windows-amd64\ngrok.exe")


async def start_redis(retries: int = 3, delay: float = 2.0) -> Optional[asyncio.subprocess.Process]:
    """
    Start Redis server as an async subprocess.
    Returns the process handle or None if it fails.
    """
    for attempt in range(1, retries + 1):
        try:
            process = await asyncio.create_subprocess_exec(
                "memurai",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.STDOUT,
            )
            await asyncio.sleep(1)  # allow startup time
            logger.info("Redis started successfully.", extra={"component": "redis"})
            return process
        except Exception as e:
            logger.error(
                f"Failed to start Redis (attempt {attempt}/{retries}): {e}",
                extra={"component": "redis"},
            )
            await asyncio.sleep(delay)
    return None


async def start_ngrok(port: int = 8000, retries: int = 5, delay: float = 2.0) -> Tuple[Optional[str], Optional[asyncio.subprocess.Process]]:
    """
    Start ngrok on the given port and return (public_url, process).
    If it fails, returns (None, None).
    """
    if not NGROK_PATH.exists():
        logger.error("Ngrok executable not found at %s", NGROK_PATH)
        return None, None

    try:
        process = await asyncio.create_subprocess_exec(
            str(NGROK_PATH), "http", str(port), "--log", "stdout",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(NGROK_PATH.parent)
        )

        url: Optional[str] = None
        for attempt in range(1, retries + 1):
            await asyncio.sleep(delay)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get("http://127.0.0.1:4040/api/tunnels") as resp:
                        data = await resp.json()
                        url = data["tunnels"][0]["public_url"]
                        logger.info(f"Ngrok tunnel ready at {url}", extra={"component": "ngrok"})
                        return url, process
            except Exception:
                logger.warning(
                    f"Ngrok tunnel not ready (attempt {attempt}/{retries})",
                    extra={"component": "ngrok"},
                )

        logger.error("Ngrok failed to provide a tunnel.", extra={"component": "ngrok"})
        return None, process

    except Exception as e:
        logger.exception("Failed to start ngrok", extra={"component": "ngrok", "error": str(e)})
        return None, None


async def stop_process(process: Optional[asyncio.subprocess.Process], name: str) -> None:
    """
    Gracefully stop a subprocess.
    """
    if process:
        try:
            process.terminate()
            await process.wait()
            logger.info(f"{name} terminated.", extra={"component": name.lower()})
        except Exception as e:
            logger.error(f"Error stopping {name}: {e}", extra={"component": name.lower()})
