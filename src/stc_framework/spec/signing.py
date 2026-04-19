"""ed25519 signature verification for STC specs.

In a regulated deployment the spec file is the compliance posture:
which rails fire, which models can be reached, which data tier goes
where. It must not be modifiable without change control and
non-repudiation.

The signing flow:

1. Release manager signs the spec file's SHA-256 digest with a
   ed25519 private key held in a code-signing HSM (or sigstore / Yubikey).
2. The public key is shipped with the deployment image (or pinned by
   hash in a runtime config).
3. At process start, :func:`verify_spec_signature` recomputes the
   digest, loads the sibling ``.sig`` file, and checks the signature.
   A mismatch prevents the STCSystem from booting.

The signing itself is implemented in the ``stc-governance sign-spec``
CLI for convenience, but operators are encouraged to use a
hardware-backed signing tool for production keys.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path


class SpecSignatureError(Exception):
    """Raised when a required spec signature is missing or invalid."""


def spec_digest(path: str | os.PathLike[str]) -> bytes:
    """Return SHA-256 of the spec file's contents."""
    return hashlib.sha256(Path(path).read_bytes()).digest()


def _load_public_key(public_key_env: str) -> bytes | None:
    raw = os.getenv(public_key_env)
    if not raw:
        return None
    try:
        return base64.urlsafe_b64decode(raw)
    except Exception as exc:
        raise SpecSignatureError(
            f"{public_key_env} is not valid base64-urlsafe: {exc}"
        ) from exc


def sign_spec(
    path: str | os.PathLike[str],
    *,
    private_key_b64: str,
) -> bytes:
    """Sign ``path`` with an ed25519 private key.

    Not used in production (operators should use a hardware signer),
    but exposed so CI / test infrastructure can produce deterministic
    signatures.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    try:
        raw = base64.urlsafe_b64decode(private_key_b64)
    except Exception as exc:
        raise SpecSignatureError(f"private key not base64-urlsafe: {exc}") from exc
    if len(raw) != 32:
        raise SpecSignatureError(f"ed25519 private key must be 32 bytes; got {len(raw)}")
    priv = Ed25519PrivateKey.from_private_bytes(raw)
    return priv.sign(spec_digest(path))


def verify_spec_signature(
    path: str | os.PathLike[str],
    *,
    signature_path: str | os.PathLike[str] | None = None,
    public_key_env: str = "STC_SPEC_PUBLIC_KEY",
    required: bool = False,
) -> None:
    """Verify that the signature at ``signature_path`` (defaults to
    ``<path>.sig``) signs the contents of ``path`` under the ed25519
    public key stored in ``STC_SPEC_PUBLIC_KEY``.

    Parameters
    ----------
    required:
        If ``True``, every failure mode (missing signature, missing
        public key, invalid signature) raises. In production,
        :class:`STCSystem` sets this to ``True``.
        If ``False``, missing-signature/missing-key quietly pass (dev
        workflow) but an actual invalid signature still raises — you
        cannot bypass a bad signature by deleting the env var.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )

    spec_path = Path(path)
    if not spec_path.exists():
        raise SpecSignatureError(f"spec file not found: {spec_path}")

    sig_path = (
        Path(signature_path)
        if signature_path is not None
        else spec_path.with_suffix(spec_path.suffix + ".sig")
    )
    sig_present = sig_path.exists()
    pub_raw = _load_public_key(public_key_env)

    if not sig_present:
        if required:
            raise SpecSignatureError(
                f"signature required but {sig_path} is missing"
            )
        return
    if pub_raw is None:
        if required:
            raise SpecSignatureError(
                f"{public_key_env} must be set to verify the spec signature"
            )
        return
    if len(pub_raw) != 32:
        raise SpecSignatureError(
            f"{public_key_env} must decode to 32 bytes; got {len(pub_raw)}"
        )

    digest = spec_digest(spec_path)
    signature = sig_path.read_bytes()

    try:
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(signature, digest)
    except InvalidSignature as exc:
        raise SpecSignatureError(
            f"spec signature {sig_path} does not verify against {spec_path}"
        ) from exc
