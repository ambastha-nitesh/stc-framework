"""Declarative fallback chain executor."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

from stc_framework.config.logging import get_logger
from stc_framework.errors import STCError

T = TypeVar("T")

_logger = get_logger(__name__)


async def run_with_fallback(
    primary: Callable[[], Awaitable[T]],
    fallbacks: Iterable[Callable[[], Awaitable[T]]],
    *,
    label: str = "call",
    on_fallback: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Invoke ``primary``; on retryable failure, walk ``fallbacks`` in order.

    Non-retryable errors are re-raised without trying fallbacks.
    """
    attempts: list[BaseException] = []

    try:
        return await primary()
    except STCError as exc:
        if not exc.retryable:
            raise
        attempts.append(exc)
        _logger.warning("fallback.primary_failed", label=label, error=str(exc))
    except Exception as exc:
        attempts.append(exc)
        _logger.warning("fallback.primary_failed", label=label, error=repr(exc))

    for idx, fn in enumerate(fallbacks, start=1):
        if on_fallback is not None and attempts:
            on_fallback(idx, attempts[-1])
        try:
            result = await fn()
            _logger.info("fallback.recovered", label=label, fallback_index=idx)
            return result
        except STCError as exc:
            if not exc.retryable:
                raise
            attempts.append(exc)
        except Exception as exc:
            attempts.append(exc)

    last = attempts[-1] if attempts else RuntimeError("no primary / fallbacks provided")
    raise last
