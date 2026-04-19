"""Infrastructure primitives: pluggable state store, session management, perf testing.

The modules here are intentionally backend-agnostic. Shipped defaults
work in-process with no external dependencies; production deployments
can swap in Redis, a database, or any backend that implements the
:class:`~stc_framework.infrastructure.store.KeyValueStore` protocol.
"""

from stc_framework.infrastructure.perf_testing import (
    DEFAULT_PROFILES,
    DEFAULT_SLOS,
    LoadConfig,
    LoadProfile,
    PerformanceTestRunner,
    SLODefinition,
)
from stc_framework.infrastructure.session_state import (
    SessionManager,
    SessionMetadata,
    usd_from_micro,
    usd_to_micro,
)
from stc_framework.infrastructure.store import (
    InMemoryStore,
    KeyValueStore,
    StoreError,
)

__all__ = [
    "DEFAULT_PROFILES",
    "DEFAULT_SLOS",
    "InMemoryStore",
    "KeyValueStore",
    "LoadConfig",
    "LoadProfile",
    "PerformanceTestRunner",
    "SLODefinition",
    "SessionManager",
    "SessionMetadata",
    "StoreError",
    "usd_from_micro",
    "usd_to_micro",
]
