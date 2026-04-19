"""Reversible token ↔ value store.

Two implementations:
- :class:`InMemoryTokenStore` — default, process-local, not durable.
- :class:`EncryptedFileTokenStore` — AES-GCM-envelope-encrypted file,
  suitable for single-process deployments and tests; keys come from
  ``STC_TOKEN_STORE_KEY`` (base64 urlsafe, 32 bytes).

All stores expose governance hooks:

- :meth:`TokenStore.prune_before` — drop entries older than a cutoff
  (used by :func:`stc_framework.governance.apply_retention`).
- :meth:`TokenStore.erase_tenant` — drop entries for a given tenant
  (used by :func:`stc_framework.governance.erase_tenant`).

``set`` optionally accepts a ``tenant_id`` keyword so the erasure
workflow can scope deletions correctly.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Protocol, runtime_checkable

from stc_framework.errors import TokenizationError


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TokenEntry:
    value: str
    tenant_id: str | None = None
    created_at: str = field(default_factory=_now_iso)


@runtime_checkable
class TokenStore(Protocol):
    def get(self, token: str) -> str | None: ...
    def set(
        self, token: str, value: str, *, tenant_id: str | None = None
    ) -> None: ...
    def delete(self, token: str) -> None: ...

    def erase_tenant(self, tenant_id: str) -> int:
        """Delete every entry associated with ``tenant_id``."""
        return 0

    def prune_before(self, cutoff: datetime) -> int:
        """Delete entries created before ``cutoff``."""
        return 0


class InMemoryTokenStore(TokenStore):
    def __init__(self) -> None:
        self._data: dict[str, TokenEntry] = {}
        self._lock = RLock()

    def get(self, token: str) -> str | None:
        with self._lock:
            entry = self._data.get(token)
            return entry.value if entry is not None else None

    def set(
        self, token: str, value: str, *, tenant_id: str | None = None
    ) -> None:
        with self._lock:
            self._data[token] = TokenEntry(value=value, tenant_id=tenant_id)

    def delete(self, token: str) -> None:
        with self._lock:
            self._data.pop(token, None)

    def erase_tenant(self, tenant_id: str) -> int:
        with self._lock:
            before = len(self._data)
            self._data = {
                k: v for k, v in self._data.items() if v.tenant_id != tenant_id
            }
            return before - len(self._data)

    def prune_before(self, cutoff: datetime) -> int:
        cutoff_iso = cutoff.isoformat()
        with self._lock:
            before = len(self._data)
            self._data = {
                k: v for k, v in self._data.items() if v.created_at >= cutoff_iso
            }
            return before - len(self._data)


class EncryptedFileTokenStore(TokenStore):
    """AES-GCM-encrypted JSON file.

    The key is read from an environment variable so it's never checked in.
    If the env var is missing the store raises :class:`TokenizationError` on
    first write, so callers can fall back to :class:`InMemoryTokenStore`.
    """

    def __init__(self, path: str | Path, key_env: str = "STC_TOKEN_STORE_KEY") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._key_env = key_env
        self._lock = RLock()
        self._data: dict[str, TokenEntry] = {}
        self._load()

    def _key(self) -> bytes:
        raw = os.getenv(self._key_env)
        if not raw:
            raise TokenizationError(
                message=(
                    f"{self._key_env} not set; cannot use encrypted token store. "
                    "Set a 32-byte base64-urlsafe key or use InMemoryTokenStore."
                ),
                downstream="sentinel",
            )
        try:
            key = base64.urlsafe_b64decode(raw)
        except Exception as exc:  # pragma: no cover
            raise TokenizationError(
                message=f"Invalid {self._key_env}: {exc}", downstream="sentinel"
            ) from exc
        if len(key) != 32:
            raise TokenizationError(
                message=f"{self._key_env} must decode to 32 bytes",
                downstream="sentinel",
            )
        return key

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            raw = self._path.read_bytes()
            nonce, ciphertext = raw[:12], raw[12:]
            key = self._key()
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
            payload = json.loads(plaintext.decode("utf-8"))
            self._data = {
                k: TokenEntry(
                    value=v["value"] if isinstance(v, dict) else v,
                    tenant_id=v.get("tenant_id") if isinstance(v, dict) else None,
                    created_at=v.get("created_at", _now_iso())
                    if isinstance(v, dict)
                    else _now_iso(),
                )
                for k, v in payload.items()
            }
        except FileNotFoundError:
            self._data = {}
        except Exception as exc:
            raise TokenizationError(
                message=f"Failed to decrypt token store: {exc}",
                downstream="sentinel",
            ) from exc

    def _persist(self) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = self._key()
        serializable = {
            k: {
                "value": v.value,
                "tenant_id": v.tenant_id,
                "created_at": v.created_at,
            }
            for k, v in self._data.items()
        }
        plaintext = json.dumps(serializable).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)

        # Write to a temp file first so a crash cannot leave a partial
        # ciphertext behind, then rename atomically with restricted perms.
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(tmp_path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(nonce + ciphertext)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise
        # chmod explicitly in case the OS ignored the open mode (Windows).
        try:
            os.chmod(tmp_path, 0o600)
        except (OSError, NotImplementedError):
            pass
        os.replace(tmp_path, self._path)

    def get(self, token: str) -> str | None:
        with self._lock:
            entry = self._data.get(token)
            return entry.value if entry is not None else None

    def set(
        self, token: str, value: str, *, tenant_id: str | None = None
    ) -> None:
        with self._lock:
            self._data[token] = TokenEntry(value=value, tenant_id=tenant_id)
            self._persist()

    def delete(self, token: str) -> None:
        with self._lock:
            if self._data.pop(token, None) is not None:
                self._persist()

    def erase_tenant(self, tenant_id: str) -> int:
        with self._lock:
            before = len(self._data)
            self._data = {
                k: v for k, v in self._data.items() if v.tenant_id != tenant_id
            }
            removed = before - len(self._data)
            if removed:
                self._persist()
            return removed

    def prune_before(self, cutoff: datetime) -> int:
        cutoff_iso = cutoff.isoformat()
        with self._lock:
            before = len(self._data)
            self._data = {
                k: v for k, v in self._data.items() if v.created_at >= cutoff_iso
            }
            removed = before - len(self._data)
            if removed:
                self._persist()
            return removed
