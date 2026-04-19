"""Virtual-key issuance and scope enforcement."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock


@dataclass
class VirtualKey:
    persona: str
    key_id: str
    secret: str
    scopes: list[str] = field(default_factory=list)
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now or datetime.now(timezone.utc)) >= self.expires_at

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes or "*" in self.scopes


class VirtualKeyManager:
    """Issues, rotates, and validates per-persona virtual keys."""

    def __init__(self, *, rotation_days: int = 90) -> None:
        self._keys: dict[str, VirtualKey] = {}
        self._lock = RLock()
        self._rotation = timedelta(days=rotation_days)

    @staticmethod
    def _new_secret() -> str:
        return secrets.token_urlsafe(32)

    def issue(self, persona: str, scopes: list[str]) -> VirtualKey:
        with self._lock:
            key = VirtualKey(
                persona=persona,
                key_id=f"sk-{persona}-{secrets.token_hex(6)}",
                secret=self._new_secret(),
                scopes=list(scopes),
                expires_at=datetime.now(timezone.utc) + self._rotation,
            )
            self._keys[key.key_id] = key
            return key

    def rotate(self, persona: str) -> VirtualKey | None:
        with self._lock:
            current = self.current_for(persona)
            if current is None:
                return None
            fresh = self.issue(persona, current.scopes)
            # Let the old key expire naturally; do not revoke immediately to
            # allow in-flight calls to finish.
            return fresh

    def current_for(self, persona: str) -> VirtualKey | None:
        with self._lock:
            candidates = [k for k in self._keys.values() if k.persona == persona and not k.is_expired()]
            if not candidates:
                return None
            return max(candidates, key=lambda k: k.issued_at)

    def authorize(self, key_id: str, scope: str) -> bool:
        with self._lock:
            key = self._keys.get(key_id)
            if key is None or key.is_expired():
                return False
            return key.has_scope(scope)

    @staticmethod
    def verify_bearer(presented: str, secret: str) -> bool:
        """Constant-time compare presented token with stored secret."""
        return hmac.compare_digest(
            hashlib.sha256(presented.encode("utf-8")).digest(),
            hashlib.sha256(secret.encode("utf-8")).digest(),
        )

    def resolve_env_placeholder(self, placeholder: str) -> str:
        """Expand ``sk-stalwart-${ENV_KEY}`` style placeholders from env."""
        if "${" not in placeholder:
            return placeholder
        start = placeholder.index("${")
        end = placeholder.index("}", start)
        var = placeholder[start + 2 : end]
        return placeholder.replace(f"${{{var}}}", os.getenv(var, ""))
