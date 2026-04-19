"""Defensive sanitizers for untrusted text that crosses trust boundaries.

Every function here is cheap, pure, and safe to call eagerly. They target
specific well-understood attack classes:

- :func:`strip_zero_width` removes invisible Unicode characters used to
  smuggle instructions past keyword filters.
- :func:`sanitize_header_value` rejects CR/LF and control characters so
  user-supplied header values cannot inject into log lines.
- :func:`sanitize_context_chunk` strips chat-markup artefacts that
  retrieved documents sometimes use to impersonate the system / user role
  to the LLM.
- :func:`safe_log_value` ensures arbitrary strings rendered into structured
  logs cannot break the log line or include embedded control sequences.
"""

from __future__ import annotations

import re
import unicodedata

# Zero-width and BiDi-override characters commonly used for injection
# smuggling (e.g. "ig<ZWJ>nore previous instructions").
_ZERO_WIDTH = {
    "\u200b",  # ZWSP
    "\u200c",  # ZWNJ
    "\u200d",  # ZWJ
    "\u200e",  # LRM
    "\u200f",  # RLM
    "\u202a",  # LRE
    "\u202b",  # RLE
    "\u202c",  # PDF
    "\u202d",  # LRO
    "\u202e",  # RLO
    "\u2060",  # WJ
    "\u2066",  # LRI
    "\u2067",  # RLI
    "\u2068",  # FSI
    "\u2069",  # PDI
    "\ufeff",  # BOM
}


def strip_zero_width(text: str) -> str:
    """Remove zero-width / BiDi-override characters."""
    if not text:
        return text
    out = []
    for ch in text:
        if ch in _ZERO_WIDTH:
            continue
        # Also drop anything the Unicode database labels as a format char
        # that has no visible effect on content.
        if unicodedata.category(ch) == "Cf":
            continue
        out.append(ch)
    return "".join(out)


_CONTROL_EXCEPT_NEWLINE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_header_value(value: str | None, *, limit: int = 256) -> str | None:
    """Return a safe version of an HTTP header value or ``None``.

    CR, LF, NUL, and other control characters are stripped to prevent log
    injection and header-splitting. The return value is truncated to
    ``limit`` characters.
    """
    if value is None:
        return None
    cleaned = value.replace("\r", "").replace("\n", "")
    cleaned = _CONTROL_EXCEPT_NEWLINE.sub("", cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    return cleaned[:limit]


# Chat-role markers and control tokens that retrieved content should not
# be allowed to smuggle into an LLM prompt.
_CHAT_MARKUP_PATTERNS = [
    re.compile(r"<\|im_(?:start|end)\|>", re.IGNORECASE),
    re.compile(r"</?s>|<\|endoftext\|>", re.IGNORECASE),
    re.compile(r"\[/?INST\]", re.IGNORECASE),
    re.compile(r"<\|system\|>|<\|assistant\|>|<\|user\|>", re.IGNORECASE),
    re.compile(r"^(?:system|assistant|user)\s*:\s*", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\[SYSTEM\s+OVERRIDE\]", re.IGNORECASE),
]


def sanitize_context_chunk(text: str) -> str:
    """Neutralize chat-role markers and zero-width tricks in retrieved text.

    Replacements are visible (``[sanitized]``) so auditors can tell a
    document tried to impersonate the system role.
    """
    if not text:
        return text
    text = strip_zero_width(text)
    for pattern in _CHAT_MARKUP_PATTERNS:
        text = pattern.sub("[sanitized]", text)
    return text


_LOG_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def safe_log_value(value: str | None, *, limit: int = 512) -> str | None:
    """Return a version of ``value`` safe to include in structured logs.

    Control characters (including newlines) are replaced so an attacker
    cannot forge additional log lines by stuffing ``\\n`` into a header.
    """
    if value is None:
        return None
    cleaned = _LOG_CONTROL.sub(" ", value)
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + "...(truncated)"
    return cleaned
