"""Request-scoped correlation context.

Uses ``contextvars`` so values flow transparently across ``await`` and
thread-pool boundaries without threading them through every function.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

_request_id: ContextVar[str | None] = ContextVar("stc_request_id", default=None)
_trace_id: ContextVar[str | None] = ContextVar("stc_trace_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("stc_tenant_id", default=None)
_persona: ContextVar[str | None] = ContextVar("stc_persona", default=None)
_prompt_version: ContextVar[str | None] = ContextVar("stc_prompt_version", default=None)

_VARS = {
    "request_id": _request_id,
    "trace_id": _trace_id,
    "tenant_id": _tenant_id,
    "persona": _persona,
    "prompt_version": _prompt_version,
}


def new_request_id() -> str:
    """Return a new opaque request id."""
    return uuid.uuid4().hex


def get_request_id() -> str | None:
    return _request_id.get()


def current_correlation() -> dict[str, str | None]:
    """Snapshot of all correlation fields."""
    return {name: var.get() for name, var in _VARS.items()}


@contextmanager
def bind_correlation(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    tenant_id: str | None = None,
    persona: str | None = None,
    prompt_version: str | None = None,
) -> Iterator[dict[str, str | None]]:
    """Context manager that binds correlation fields for its lifetime.

    Fields left as ``None`` are not changed. Values are restored on exit.
    """
    tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = []
    updates = {
        "request_id": request_id,
        "trace_id": trace_id,
        "tenant_id": tenant_id,
        "persona": persona,
        "prompt_version": prompt_version,
    }
    try:
        for name, value in updates.items():
            if value is not None:
                tokens.append((_VARS[name], _VARS[name].set(value)))
        yield current_correlation()
    finally:
        for var, tok in reversed(tokens):
            var.reset(tok)
