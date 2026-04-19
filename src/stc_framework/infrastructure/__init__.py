"""Infrastructure primitives: pluggable state store, session management, perf testing.

The modules here are intentionally backend-agnostic. Shipped defaults
work in-process with no external dependencies; production deployments
can swap in Redis, a database, or any backend that implements the
:class:`~stc_framework.infrastructure.store.KeyValueStore` protocol.
"""

from stc_framework.infrastructure.store import (
    InMemoryStore,
    KeyValueStore,
    StoreError,
)

__all__ = ["InMemoryStore", "KeyValueStore", "StoreError"]
