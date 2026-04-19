"""Surrogate tokenization.

Sensitive values are replaced with opaque tokens of the form
``STC_TOK_<12hex>`` that are reversible via a :class:`TokenStore`. The
mapping uses HMAC-SHA256 so the same value maps to the same token within a
given HMAC key (supporting deduplication / caching) but is not guessable
without the key.

Security properties
-------------------
- The HMAC key MUST be provided via the environment variable named in
  ``key_env`` for the tokenizer to produce production-grade surrogates.
- If no key is configured, the tokenizer derives a **per-process random**
  key the first time it is used. This means different processes will
  produce different tokens for the same value (reducing cross-process
  correlation) and tokens cannot be pre-computed offline by an attacker
  who does not have memory access.
- Setting ``STC_TOKENIZATION_STRICT=1`` promotes a missing key to a hard
  failure, which is the recommended posture in production. When
  ``strict=True`` is passed explicitly the constructor enforces the
  same.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading

from stc_framework.config.logging import get_logger
from stc_framework.errors import TokenizationError
from stc_framework.sentinel.token_store import TokenStore

_logger = get_logger(__name__)


class Tokenizer:
    def __init__(
        self,
        store: TokenStore,
        *,
        key_env: str = "STC_TOKENIZATION_KEY",
        reversible: bool = True,
        strict: bool | None = None,
    ) -> None:
        self._store = store
        self._key_env = key_env
        self._reversible = reversible
        # When strict is unset, fall back to the STC_TOKENIZATION_STRICT
        # env var so operators can switch into production-grade behaviour
        # without code changes.
        if strict is None:
            strict = os.getenv("STC_TOKENIZATION_STRICT", "").lower() in {"1", "true", "yes"}
        self._strict = strict
        self._ephemeral_key: bytes | None = None
        self._key_lock = threading.Lock()

    def _hmac_key(self) -> bytes:
        raw = os.getenv(self._key_env)
        if raw:
            return raw.encode("utf-8")
        if self._strict:
            raise TokenizationError(
                message=(
                    f"{self._key_env} is not set and strict mode is enabled; "
                    "refusing to produce surrogate tokens with a derived key."
                ),
                downstream="sentinel",
            )
        # Lazy initialization of an ephemeral key — a new random key per
        # process, cached for the lifetime of the Tokenizer so the same
        # value continues to map to the same token within this process.
        with self._key_lock:
            if self._ephemeral_key is None:
                self._ephemeral_key = secrets.token_bytes(32)
                _logger.warning(
                    "tokenization.ephemeral_key_generated",
                    reason=f"{self._key_env} not set; tokens are not stable across processes",
                )
            return self._ephemeral_key

    def tokenize(self, value: str, *, tenant_id: str | None = None) -> str:
        """Return an opaque surrogate token for ``value``.

        ``tenant_id`` is stored alongside the token so the right-to-erasure
        workflow can find and delete every token a tenant produced.
        """
        if not value:
            return value
        digest = hmac.new(self._hmac_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()
        token = f"STC_TOK_{digest[:12]}"
        if self._reversible:
            self._store.set(token, value, tenant_id=tenant_id)
        return token

    def detokenize(self, token: str) -> str:
        if not token.startswith("STC_TOK_"):
            return token
        if not self._reversible:
            raise TokenizationError(
                message="Tokenizer is configured as one-way; cannot detokenize.",
                downstream="sentinel",
            )
        value = self._store.get(token)
        if value is None:
            raise TokenizationError(message=f"Unknown token {token}", downstream="sentinel")
        return value

    def detokenize_text(self, text: str) -> str:
        """Replace every known token in ``text`` with its original value."""
        if not self._reversible or "STC_TOK_" not in text:
            return text
        import re

        pattern = re.compile(r"STC_TOK_[0-9a-f]{12}")

        def repl(match: re.Match[str]) -> str:
            token = match.group(0)
            value = self._store.get(token)
            return value if value is not None else token

        return pattern.sub(repl, text)
