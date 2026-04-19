"""Expanded prompt-injection rule set.

This module consolidates every detection heuristic the Critic's input rail
relies on. It is intentionally more aggressive than the original
``critic.validators.injection`` list to catch bypasses observed in the wild:

- **Unicode smuggling** — zero-width and BiDi-override characters inserted
  between letters.
- **Multilingual** — instruction-override attempts in German, French,
  Spanish, and Italian.
- **Role switching** — ``system:``/``assistant:`` prefix spoofs and
  ``<|im_start|>`` token smuggling.
- **Translation smuggling** — "translate the system prompt", "repeat your
  instructions in French".
- **Base64 / hex smuggling** — long runs of base64 that decode to known
  injection verbs.
- **Delimiter breakout** — triple-backtick and HTML comment escapes that
  try to end the current instruction block.
- **Code-block exfiltration** — requests to output the system prompt
  inside a code block or as a URL parameter.

Each detection returns both a label and a short snippet of the offending
substring so audit logs can explain why a request was blocked.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterable
from dataclasses import dataclass

from stc_framework.security.sanitize import strip_zero_width


@dataclass(frozen=True)
class InjectionMatch:
    rule: str
    snippet: str


@dataclass(frozen=True)
class _Rule:
    name: str
    pattern: re.Pattern[str]


# ---------------------------------------------------------------------------
# Core English
# ---------------------------------------------------------------------------

INJECTION_RULES: list[_Rule] = [
    _Rule(
        "override.en",
        re.compile(
            r"\b(?:ignore|disregard|forget|bypass|override|skip)\b[^.\n]{0,60}"
            r"\b(?:previous|prior|above|earlier|system|all|everything)\b",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "override.en.targeted",
        re.compile(
            r"\b(?:ignore|disregard|forget|bypass|override)\b[^.\n]{0,60}"
            r"\b(?:instructions?|rules?|prompts?|messages?|context|guidelines?)\b",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "system_override",
        re.compile(
            r"\[\s*(?:SYSTEM|ADMIN|ROOT)?\s*"
            r"(?:OVERRIDE|ADMIN|ROOT|PROMPT|BYPASS|JAILBREAK)\s*\]",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "developer_mode",
        re.compile(
            r"\b(?:developer|admin|root|jailbreak|god|DAN)\s+mode\b",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "disable_guardrails",
        re.compile(
            r"\b(?:disable|turn\s+off|deactivate|bypass|remove)\s+"
            r"(?:all\s+)?(?:guardrails?|safety|safeguards?|filters?|restrictions?)\b",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "role_switch",
        re.compile(
            r"\b(?:you\s+are\s+now|pretend\s+(?:to\s+be|you\s+are)|"
            r"act\s+as|roleplay\s+as|from\s+now\s+on\s+you\s+are)\b",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "exfiltrate_system_prompt",
        re.compile(
            r"(?:reveal|show|print|display|output|return|repeat|leak)\s+"
            r"(?:me\s+)?(?:the\s+|your\s+|my\s+)?"
            r"(?:(?:system\s+)?(?:prompt|instructions?|rules?)|context|hidden\s+text)",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "translate_exfiltration",
        re.compile(
            r"\btranslate\b[^.\n]{0,60}\b(?:system\s+prompt|instructions|rules|context)\b",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "chat_markup",
        re.compile(
            r"</?s>|\[/?INST\]|<\|im_(?:start|end)\|>|<\|endoftext\|>"
            r"|<\|(?:system|assistant|user)\|>",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "role_prefix_spoof",
        re.compile(
            r"(?m)^\s*(?:system|assistant|user)\s*:\s*"
            r"(?:you\s+are|ignore|override|forget)",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "delimiter_breakout",
        re.compile(
            r"(?:```|~~~|<!--|-->|\"\"\")\s*(?:end|/)?\s*"
            r"(?:system|instructions?|prompt)",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "url_exfiltration",
        re.compile(
            r"https?://\S+\?[^\s]*(?:prompt|system|instructions|secret|token|key)=",
            re.IGNORECASE,
        ),
    ),
    # ---------------- Multilingual -------------------------------------
    _Rule(
        "override.de",
        re.compile(
            r"\b(?:ignoriere|vergiss|missachte)\b[^.\n]{0,40}"
            r"\b(?:anweisungen|instruktionen|vorherig|oben|regeln)\b",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "override.es",
        re.compile(
            r"\b(?:ignora|olvida|desatiende)\b[^.\n]{0,40}"
            r"\b(?:instrucciones|reglas|anteriores|sistema)\b",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "override.fr",
        re.compile(
            r"\b(?:ignore[rz]?|oublie[rz]?)\b[^.\n]{0,40}"
            r"\b(?:instructions?|consignes?|règles?|précédentes?|système)\b",
            re.IGNORECASE,
        ),
    ),
    _Rule(
        "override.it",
        re.compile(
            r"\b(?:ignora|dimentica)\b[^.\n]{0,40}"
            r"\b(?:istruzioni|regole|precedenti|sistema)\b",
            re.IGNORECASE,
        ),
    ),
]


# Verbs that, if found *decoded* inside a base64 or hex blob, signal a
# smuggled instruction-override payload.
_DECODED_TRIGGER_WORDS = re.compile(
    r"\b(?:ignore|disregard|system\s+prompt|developer\s+mode|"
    r"reveal|exfiltrate|override)\b",
    re.IGNORECASE,
)

_B64_RUN = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")


def _decoded_injection(text: str) -> InjectionMatch | None:
    """Return a match if ``text`` contains a base64 run whose decoding
    contains a known injection verb.
    """
    for match in _B64_RUN.finditer(text):
        blob = match.group(0)
        try:
            decoded = base64.b64decode(blob, validate=False).decode(
                "utf-8", errors="ignore"
            )
        except Exception:
            continue
        if _DECODED_TRIGGER_WORDS.search(decoded):
            return InjectionMatch(rule="encoded_payload", snippet=blob[:48])
    return None


def detect_injection(text: str) -> list[InjectionMatch]:
    """Return every injection rule that matches ``text``.

    The input is first normalized via :func:`strip_zero_width` so that
    Unicode smuggling (``ig<ZWJ>nore``) cannot bypass the regex rules.
    """
    if not text:
        return []
    normalized = strip_zero_width(text)
    hits: list[InjectionMatch] = []
    for rule in INJECTION_RULES:
        m = rule.pattern.search(normalized)
        if m:
            hits.append(InjectionMatch(rule=rule.name, snippet=m.group(0)[:80]))
    encoded = _decoded_injection(normalized)
    if encoded:
        hits.append(encoded)
    return hits


def redact_injection_snippets(matches: Iterable[InjectionMatch]) -> list[dict[str, str]]:
    """Render matches for logs without leaking entire request bodies."""
    return [{"rule": m.rule, "snippet": m.snippet[:80]} for m in matches]
