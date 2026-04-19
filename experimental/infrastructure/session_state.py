"""
STC Framework — Session State Manager
infrastructure/session_state.py

Production session state management with pluggable backends:
  - Redis Cluster (production): distributed, persistent, HA
  - In-memory (development): fast, no dependencies

Manages:
  - Conversation context (LangGraph state)
  - Surrogate token maps (encrypted)
  - Per-session cost tracking
  - Session lifecycle (create, load, save, destroy)

All state is keyed by session_id with configurable TTL.
Supports atomic operations for cost counters and rate limiters.
"""

import json
import time
import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stc.infrastructure.session_state")


@dataclass
class SessionMetadata:
    session_id: str
    created_at: float
    last_accessed: float
    request_count: int = 0
    total_tokens: int = 0
    data_tier: str = "public"
    user_id: str = ""


class StateBackend(ABC):
    """Abstract backend for session state storage."""

    @abstractmethod
    def get(self, key: str) -> Optional[str]: ...
    @abstractmethod
    def set(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> bool: ...
    @abstractmethod
    def delete(self, key: str) -> bool: ...
    @abstractmethod
    def exists(self, key: str) -> bool: ...
    @abstractmethod
    def incr(self, key: str, amount: int = 1) -> int: ...
    @abstractmethod
    def expire(self, key: str, ttl_seconds: int) -> bool: ...
    @abstractmethod
    def keys(self, pattern: str) -> List[str]: ...
    @abstractmethod
    def health_check(self) -> Dict[str, Any]: ...


class RedisBackend(StateBackend):
    """Redis Cluster backend for production."""

    def __init__(self, url: str = "redis://localhost:6379", prefix: str = "stc"):
        self.prefix = prefix
        self._client = None
        self._url = url

    def _c(self):
        if self._client is None:
            try:
                import redis
                self._client = redis.from_url(self._url, decode_responses=True)
                self._client.ping()
            except ImportError:
                raise ImportError("redis package required: pip install redis")
            except Exception as e:
                logger.error(f"Redis connection failed: {e}")
                raise
        return self._client

    def _k(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    def get(self, key):
        try: return self._c().get(self._k(key))
        except Exception as e: logger.error(f"Redis GET failed: {e}"); return None

    def set(self, key, value, ttl_seconds=None):
        try:
            if ttl_seconds:
                return bool(self._c().setex(self._k(key), ttl_seconds, value))
            return bool(self._c().set(self._k(key), value))
        except Exception as e:
            logger.error(f"Redis SET failed: {e}"); return False

    def delete(self, key):
        try: return bool(self._c().delete(self._k(key)))
        except Exception as e: logger.error(f"Redis DEL failed: {e}"); return False

    def exists(self, key):
        try: return bool(self._c().exists(self._k(key)))
        except: return False

    def incr(self, key, amount=1):
        try: return self._c().incrby(self._k(key), amount)
        except Exception as e: logger.error(f"Redis INCR failed: {e}"); return 0

    def expire(self, key, ttl_seconds):
        try: return bool(self._c().expire(self._k(key), ttl_seconds))
        except: return False

    def keys(self, pattern):
        try:
            full = self._c().keys(self._k(pattern))
            prefix_len = len(self.prefix) + 1
            return [k[prefix_len:] for k in full]
        except: return []

    def health_check(self):
        try:
            self._c().ping()
            info = self._c().info("memory")
            return {
                "backend": "redis", "status": "healthy",
                "memory_used": info.get("used_memory_human", "unknown"),
            }
        except Exception as e:
            return {"backend": "redis", "status": "unreachable", "error": str(e)}


class InMemoryBackend(StateBackend):
    """In-memory backend for development. Thread-safe."""

    def __init__(self):
        self._store: Dict[str, tuple] = {}  # key → (value, expire_at)
        self._counters: Dict[str, int] = {}
        self._lock = threading.Lock()

    def _is_expired(self, key):
        if key in self._store:
            val, expire_at = self._store[key]
            if expire_at and time.time() > expire_at:
                del self._store[key]
                return True
        return False

    def get(self, key):
        with self._lock:
            self._is_expired(key)
            if key in self._store:
                return self._store[key][0]
            return None

    def set(self, key, value, ttl_seconds=None):
        with self._lock:
            expire_at = time.time() + ttl_seconds if ttl_seconds else None
            self._store[key] = (value, expire_at)
            return True

    def delete(self, key):
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            self._counters.pop(key, None)
            return False

    def exists(self, key):
        with self._lock:
            self._is_expired(key)
            return key in self._store or key in self._counters

    def incr(self, key, amount=1):
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + amount
            return self._counters[key]

    def expire(self, key, ttl_seconds):
        with self._lock:
            if key in self._store:
                val, _ = self._store[key]
                self._store[key] = (val, time.time() + ttl_seconds)
                return True
            return False

    def keys(self, pattern):
        import fnmatch
        with self._lock:
            # Clean expired
            expired = [k for k in self._store if self._is_expired(k)]
            all_keys = list(self._store.keys()) + list(self._counters.keys())
            return [k for k in all_keys if fnmatch.fnmatch(k, pattern)]

    def health_check(self):
        return {
            "backend": "memory", "status": "healthy",
            "keys": len(self._store) + len(self._counters),
        }


# ── Session Manager ─────────────────────────────────────────────────────────

class SessionManager:
    """
    Manages session lifecycle and state for the STC pipeline.

    Session state structure in Redis:
        stc:session:{id}:context   → JSON conversation context
        stc:session:{id}:tokens    → Encrypted surrogate token map
        stc:session:{id}:meta      → Session metadata
        stc:cost:{date}:{persona}  → Daily cost counter (atomic)
        stc:rate:{persona}:{window} → Rate limiter counter

    Usage:
        sm = SessionManager(backend=InMemoryBackend())
        session = sm.create_session(user_id="advisor-123")
        sm.save_context(session.session_id, {"messages": [...]})
        ctx = sm.load_context(session.session_id)
        sm.destroy_session(session.session_id)
    """

    DEFAULT_TTL = 1800  # 30 minutes idle timeout

    def __init__(self, backend: Optional[StateBackend] = None,
                 default_ttl: int = 1800, audit_callback=None):
        self.backend = backend or InMemoryBackend()
        self.default_ttl = default_ttl
        self._audit_callback = audit_callback

    @classmethod
    def from_spec(cls, spec: Dict[str, Any] = None, audit_callback=None) -> "SessionManager":
        spec = spec or {}
        infra = spec.get("infrastructure", {})
        redis_url = infra.get("redis_url")

        if redis_url:
            try:
                backend = RedisBackend(url=redis_url)
                backend.health_check()  # Verify connectivity
                return cls(backend=backend, audit_callback=audit_callback)
            except Exception as e:
                logger.warning(f"Redis unavailable ({e}), falling back to in-memory")

        return cls(backend=InMemoryBackend(), audit_callback=audit_callback)

    def create_session(self, user_id: str = "", data_tier: str = "public") -> SessionMetadata:
        """Create a new session."""
        session_id = hashlib.sha256(
            f"{user_id}:{time.time()}:{id(self)}".encode()
        ).hexdigest()[:24]

        now = time.time()
        meta = SessionMetadata(
            session_id=session_id, created_at=now, last_accessed=now,
            user_id=user_id, data_tier=data_tier,
        )

        # Store metadata
        self.backend.set(
            f"session:{session_id}:meta",
            json.dumps({
                "session_id": session_id,
                "created_at": now,
                "last_accessed": now,
                "request_count": 0,
                "total_tokens": 0,
                "data_tier": data_tier,
                "user_id": user_id,
            }),
            self.default_ttl
        )

        # Initialize empty context
        self.backend.set(f"session:{session_id}:context", "{}", self.default_ttl)

        self._emit("session_created", session_id, {"user_id": user_id, "data_tier": data_tier})
        return meta

    def save_context(self, session_id: str, context: Dict[str, Any]) -> bool:
        """Save conversation context for a session."""
        key = f"session:{session_id}:context"
        success = self.backend.set(key, json.dumps(context), self.default_ttl)

        # Update last_accessed in metadata
        meta_key = f"session:{session_id}:meta"
        raw = self.backend.get(meta_key)
        if raw:
            meta = json.loads(raw)
            meta["last_accessed"] = time.time()
            meta["request_count"] = meta.get("request_count", 0) + 1
            self.backend.set(meta_key, json.dumps(meta), self.default_ttl)

        return success

    def load_context(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load conversation context for a session."""
        raw = self.backend.get(f"session:{session_id}:context")
        if raw:
            # Refresh TTL
            self.backend.expire(f"session:{session_id}:context", self.default_ttl)
            self.backend.expire(f"session:{session_id}:meta", self.default_ttl)
            return json.loads(raw)
        return None

    def save_token_map(self, session_id: str, encrypted_blob: bytes) -> bool:
        """Save encrypted surrogate token map."""
        import base64
        encoded = base64.b64encode(encrypted_blob).decode()
        return self.backend.set(
            f"session:{session_id}:tokens", encoded, self.default_ttl)

    def load_token_map(self, session_id: str) -> Optional[bytes]:
        """Load encrypted surrogate token map."""
        import base64
        raw = self.backend.get(f"session:{session_id}:tokens")
        if raw:
            self.backend.expire(f"session:{session_id}:tokens", self.default_ttl)
            return base64.b64decode(raw)
        return None

    def destroy_session(self, session_id: str):
        """Destroy all state for a session (session end)."""
        for suffix in ["context", "tokens", "meta"]:
            self.backend.delete(f"session:{session_id}:{suffix}")
        self._emit("session_destroyed", session_id, {})

    def get_session_meta(self, session_id: str) -> Optional[SessionMetadata]:
        """Get session metadata."""
        raw = self.backend.get(f"session:{session_id}:meta")
        if raw:
            data = json.loads(raw)
            return SessionMetadata(**data)
        return None

    def session_exists(self, session_id: str) -> bool:
        return self.backend.exists(f"session:{session_id}:meta")

    # ── Atomic Counters ─────────────────────────────────────────────────

    def increment_cost(self, persona: str, tokens: int,
                       cost_per_token: float = 0.00001) -> float:
        """Atomically increment daily cost for a persona."""
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"cost:{date}:{persona}"
        # Store cost in micro-dollars for integer precision
        micro_cost = int(tokens * cost_per_token * 1_000_000)
        new_total = self.backend.incr(key, micro_cost)
        self.backend.expire(key, 86400 * 2)  # 2-day TTL
        return new_total / 1_000_000

    def get_daily_cost(self, persona: str) -> float:
        """Get current daily cost for a persona."""
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw = self.backend.get(f"cost:{date}:{persona}")
        return int(raw) / 1_000_000 if raw else 0.0

    def check_rate_limit(self, persona: str, max_rpm: int) -> bool:
        """
        Check and increment rate limiter. Returns True if allowed.
        Uses sliding window per minute.
        """
        minute = int(time.time() / 60)
        key = f"rate:{persona}:{minute}"
        current = self.backend.incr(key, 1)
        if current == 1:
            self.backend.expire(key, 120)  # 2-minute TTL
        return current <= max_rpm

    # ── Health & Stats ──────────────────────────────────────────────────

    def active_sessions(self) -> int:
        """Count active sessions."""
        return len(self.backend.keys("session:*:meta"))

    def health(self) -> Dict[str, Any]:
        backend_health = self.backend.health_check()
        return {
            "backend": backend_health,
            "active_sessions": self.active_sessions(),
            "default_ttl": self.default_ttl,
        }

    def _emit(self, event_type, session_id, details):
        if self._audit_callback:
            self._audit_callback({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "component": "infrastructure.session_state",
                "event_type": event_type,
                "session_id": session_id,
                "details": details,
            })


# ── Demo ────────────────────────────────────────────────────────────────────

def demo():
    print("=" * 70)
    print("STC Session State Manager — Demo")
    print("=" * 70)

    audit_log = []
    sm = SessionManager(
        backend=InMemoryBackend(),
        default_ttl=300,
        audit_callback=lambda e: audit_log.append(e),
    )

    # Create sessions
    print("\n▸ Creating sessions...")
    s1 = sm.create_session(user_id="advisor-001", data_tier="internal")
    s2 = sm.create_session(user_id="advisor-002", data_tier="restricted")
    print(f"  Session 1: {s1.session_id} (user={s1.user_id}, tier={s1.data_tier})")
    print(f"  Session 2: {s2.session_id} (user={s2.user_id}, tier={s2.data_tier})")

    # Save and load context
    print("\n▸ Saving conversation context...")
    context1 = {
        "messages": [
            {"role": "user", "content": "What was ACME revenue?"},
            {"role": "assistant", "content": "ACME reported $5.2B in FY2024."},
        ],
        "retrieved_docs": ["acme_10k_fy2024.txt"],
    }
    sm.save_context(s1.session_id, context1)

    loaded = sm.load_context(s1.session_id)
    assert loaded == context1
    print(f"  ✓ Context saved and loaded ({len(loaded['messages'])} messages)")

    # Session isolation test
    print("\n▸ Session isolation test...")
    ctx2 = sm.load_context(s2.session_id)
    assert ctx2 == {}
    print(f"  ✓ Session 2 has empty context (isolated from Session 1)")

    # Token map
    print("\n▸ Encrypted token map...")
    import os
    fake_blob = os.urandom(128)
    sm.save_token_map(s1.session_id, fake_blob)
    loaded_blob = sm.load_token_map(s1.session_id)
    assert loaded_blob == fake_blob
    print(f"  ✓ Token map round-trip: {len(fake_blob)} bytes")

    # Cost tracking
    print("\n▸ Atomic cost tracking...")
    for _ in range(5):
        cost = sm.increment_cost("stalwart", tokens=500, cost_per_token=0.00003)
    print(f"  Stalwart daily cost after 5 requests (2500 tokens): ${cost:.4f}")

    for _ in range(2):
        cost_t = sm.increment_cost("trainer", tokens=1000, cost_per_token=0.00006)
    print(f"  Trainer daily cost after 2 requests (2000 tokens): ${cost_t:.4f}")

    # Rate limiting
    print("\n▸ Rate limiting (max 3 RPM)...")
    for i in range(5):
        allowed = sm.check_rate_limit("stalwart", max_rpm=3)
        print(f"  Request {i+1}: {'✓ allowed' if allowed else '✗ rate limited'}")

    # Session metadata
    print("\n▸ Session metadata...")
    meta = sm.get_session_meta(s1.session_id)
    print(f"  Session 1: requests={meta.request_count}, user={meta.user_id}")

    # Active sessions
    print(f"\n▸ Active sessions: {sm.active_sessions()}")

    # Health
    print("\n▸ Health check:")
    health = sm.health()
    print(f"  Backend: {health['backend']['status']} ({health['backend']['backend']})")
    print(f"  Active sessions: {health['active_sessions']}")
    print(f"  Default TTL: {health['default_ttl']}s")

    # Destroy session
    print("\n▸ Destroying session 1...")
    sm.destroy_session(s1.session_id)
    assert not sm.session_exists(s1.session_id)
    print(f"  ✓ Session 1 destroyed and verified")
    print(f"  Active sessions: {sm.active_sessions()}")

    print(f"\n▸ Audit events: {len(audit_log)}")

    print("\n" + "=" * 70)
    print("✓ Session state manager demo complete")
    print("=" * 70)


if __name__ == "__main__":
    demo()
