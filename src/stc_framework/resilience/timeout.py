"""Async timeout helper.

``asyncio.timeout`` was added in Python 3.11. On 3.10 we fall back to
``asyncio.wait_for`` via a small shim that preserves the context-manager
ergonomics.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

_HAS_NATIVE_TIMEOUT = sys.version_info >= (3, 11)


@asynccontextmanager
async def atimeout(seconds: float) -> AsyncIterator[None]:
    """Context manager that raises :class:`asyncio.TimeoutError` on overrun.

    Works on Python 3.10+ — uses ``asyncio.timeout`` on 3.11+ and falls
    back to a compatible task-cancellation shim on 3.10.
    """
    if _HAS_NATIVE_TIMEOUT:
        try:
            async with asyncio.timeout(seconds):
                yield
        except asyncio.CancelledError:
            raise
        return

    # Python 3.10 fallback: schedule a cancellation task.
    loop = asyncio.get_running_loop()
    current_task = asyncio.current_task()
    if current_task is None:
        # Not running inside a task (rare); yield without a timer.
        yield
        return

    cancelled = False

    def _cancel() -> None:
        nonlocal cancelled
        cancelled = True
        current_task.cancel()

    handle = loop.call_later(seconds, _cancel)
    try:
        yield
    except asyncio.CancelledError:
        if cancelled:
            raise asyncio.TimeoutError() from None
        raise
    finally:
        handle.cancel()
