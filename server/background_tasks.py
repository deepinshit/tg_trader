import asyncio
import logging
from typing import Set, Callable, Any, Awaitable, Union

logger = logging.getLogger(__name__)

# Global task registry
background_tasks: Set[asyncio.Task] = set()

def create_background_task(
    coro_or_func: Union[Awaitable, Callable[..., Awaitable]],
    *args: Any,
    name: str = None,
    **kwargs: Any,
) -> asyncio.Task:
    """
    Create and track background tasks so they can be cancelled on shutdown.

    Args:
        coro_or_func: Either an *awaitable* (already a coroutine object),
                      or an async callable to be invoked with args/kwargs.
        *args: Positional arguments if coro_or_func is a callable.
        name: Optional name for the task (helps with debugging/logging).
        **kwargs: Keyword arguments if coro_or_func is a callable.

    Returns:
        asyncio.Task: The created and tracked task.
    """
    # If user passed a coroutine object directly
    if asyncio.iscoroutine(coro_or_func):
        coro = coro_or_func
    else:
        # Assume it's a callable that returns a coroutine
        coro = coro_or_func(*args, **kwargs)

    task = asyncio.create_task(coro, name=name)
    background_tasks.add(task)

    def _done_callback(t: asyncio.Task) -> None:
        background_tasks.discard(t)
        try:
            t.result()  # will raise if exception
            logger.debug("Background task %s completed successfully.", name or t.get_name())
        except asyncio.CancelledError:
            logger.debug("Background task %s was cancelled.", name or t.get_name())
        except Exception as e:
            logger.error(
                "Background task %s failed: %s",
                name or t.get_name(),
                e,
                exc_info=True,
            )

    task.add_done_callback(_done_callback)
    return task

async def shutdown_background_tasks(timeout: float = 10.0) -> None:
    if not background_tasks:
        return

    logger.info("Shutting down %d background tasks...", len(background_tasks))

    # Ask them to stop
    for task in list(background_tasks):
        task.cancel()

    # Give them a chance to finish
    done, pending = await asyncio.wait(background_tasks, timeout=timeout)

    for t in done:
        try:
            await t  # propagate exception if any
        except asyncio.CancelledError:
            logger.debug("Task %s cancelled cleanly.", t.get_name())
        except Exception as e:
            logger.error("Task %s raised: %s", t.get_name(), e, exc_info=True)

    if pending:
        logger.warning("Some tasks did not exit before timeout: %s", [t.get_name() for t in pending])
