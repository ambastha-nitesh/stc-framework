"""Tenacity-based retry decorators with OTel + metrics integration."""

from __future__ import annotations

import asyncio
import random
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

from stc_framework.config.logging import get_logger
from stc_framework.errors import (
    EmbeddingError,
    LLMError,
    LLMQuotaExceeded,
    RetryExhausted,
    STCError,
    VectorStoreError,
)
from stc_framework.observability.metrics import get_metrics

_logger = get_logger(__name__)

T = TypeVar("T")


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, LLMQuotaExceeded):
        return False
    if isinstance(exc, STCError):
        return exc.retryable
    # Network-level exceptions are transient.
    import httpx

    if isinstance(
        exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError)
    ):
        return True
    if isinstance(exc, asyncio.TimeoutError):
        return True
    return False


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    downstream: str,
    max_attempts: int = 3,
    base_delay: float = 0.25,
    max_delay: float = 8.0,
) -> T:
    """Run an async callable with exponential backoff + full jitter.

    Parameters
    ----------
    fn:
        A zero-argument async callable.
    downstream:
        Label used for metrics (``stc_retry_attempts_total``).
    max_attempts:
        Total attempts including the first.
    base_delay, max_delay:
        Exponential backoff parameters in seconds.
    """
    metrics = get_metrics()
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = await fn()
            if attempt > 1:
                metrics.retry_attempts_total.labels(downstream=downstream, outcome="success").inc()
            return result
        except BaseException as exc:
            last_exc = exc
            if not _is_transient(exc) or attempt == max_attempts:
                metrics.retry_attempts_total.labels(downstream=downstream, outcome="failed").inc()
                if isinstance(exc, STCError):
                    raise
                if attempt == max_attempts:
                    raise RetryExhausted(
                        message=f"Retries exhausted for {downstream}",
                        downstream=downstream,
                        last_error=repr(exc),
                        retryable=False,
                    ) from exc
                raise

            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = random.uniform(0, delay)  # noqa: S311 - jitter, not crypto
            metrics.retry_attempts_total.labels(downstream=downstream, outcome="retry").inc()
            _logger.warning(
                "retry.backoff",
                downstream=downstream,
                attempt=attempt,
                next_delay_sec=round(delay, 3),
                error=repr(exc),
            )
            await asyncio.sleep(delay)

    # Should not reach here, but satisfy type checkers.
    assert last_exc is not None
    raise last_exc


def retry_transient(
    *, downstream: str, max_attempts: int = 3
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator: retry a coroutine on transient errors."""

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await with_retry(
                lambda: fn(*args, **kwargs), downstream=downstream, max_attempts=max_attempts
            )

        return wrapper

    return decorator


# Named aliases for domain-specific retries. They share machinery but
# different defaults / downstream labels are clearer at call sites.


def retry_llm(
    max_attempts: int = 3,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    return retry_transient(downstream="llm", max_attempts=max_attempts)


def retry_vector(
    max_attempts: int = 3,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    return retry_transient(downstream="vector_store", max_attempts=max_attempts)


def retry_embedding(
    max_attempts: int = 3,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    return retry_transient(downstream="embedding", max_attempts=max_attempts)


__all__ = [
    "EmbeddingError",
    "LLMError",
    "VectorStoreError",
    "retry_embedding",
    "retry_llm",
    "retry_transient",
    "retry_vector",
    "with_retry",
]
