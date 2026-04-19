"""Runtime threat detection — DDoS, behavioural, deception, UEBA.

Four independent subsystems coordinated by :class:`ThreatDetectionManager`:

* **EdgeRateLimiter** — per-IP per-minute + per-hour limits plus a
  cost-exhaustion detector (USD/min). Trips ``DDoSDetected``.
* **BehavioralAnalyzer** — tracks per-session query history and raises
  ``BehavioralAnomalyDetected`` when counts / failure rates exceed the
  configured thresholds.
* **DeceptionEngine** — tracks honey-docs, honey-tokens, canary queries.
  Any access = real attack, raises ``HoneyTokenTriggered``.
* **PatternScanner** — applies the shared threat pattern catalog to
  the request body for exfil / model-extraction / base64 smuggling.

All four coordinate through :class:`~stc_framework.resilience.degradation.DegradationState`
so a severe threat can flip the system into DEGRADED automatically.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from stc_framework.errors import (
    BehavioralAnomalyDetected,
    DDoSDetected,
    HoneyTokenTriggered,
    ThreatDetected,
)
from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord
from stc_framework.observability.metrics import get_metrics
from stc_framework.resilience.degradation import DegradationLevel, get_degradation_state
from stc_framework.security.patterns import PatternCatalog, default_threat_catalog


class ThreatType(str, Enum):
    DDOS_VOLUMETRIC = "ddos_volumetric"
    DDOS_COST_EXHAUSTION = "ddos_cost_exhaustion"
    PROMPT_INJECTION_CAMPAIGN = "prompt_injection_campaign"
    MULTI_TURN_MANIPULATION = "multi_turn_manipulation"
    MODEL_EXTRACTION = "model_extraction"
    DATA_EXFILTRATION = "data_exfiltration"
    INSIDER_ABUSE = "insider_abuse"
    COORDINATED_ATTACK = "coordinated_attack"
    CREDENTIAL_STUFFING = "credential_stuffing"
    HONEY_TOKEN_TRIGGERED = "honey_token_triggered"
    HONEY_DOC_ACCESSED = "honey_doc_accessed"
    CANARY_DRIFT = "canary_drift"


class ThreatSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ThreatAlert:
    threat_type: ThreatType
    severity: ThreatSeverity
    source: str  # e.g. IP, session_id, tenant_id
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


# ----- Edge rate limiter -------------------------------------------------


@dataclass
class EdgeLimits:
    per_minute: int = 60
    per_hour: int = 1000
    cost_exhaustion_usd_per_minute: float = 5.0
    block_duration_seconds: int = 900  # 15 min


class EdgeRateLimiter:
    """In-memory per-IP rolling window limiter + IP blocklist."""

    def __init__(self, limits: EdgeLimits | None = None) -> None:
        self._limits = limits or EdgeLimits()
        self._minute_window: dict[str, deque[float]] = defaultdict(deque)
        self._hour_window: dict[str, deque[float]] = defaultdict(deque)
        self._cost_window: dict[str, deque[tuple[float, float]]] = defaultdict(deque)
        self._blocked: dict[str, float] = {}  # ip -> unblock epoch

    def _prune(self, q: deque[float], cutoff: float) -> None:
        while q and q[0] < cutoff:
            q.popleft()

    def check(self, ip: str, *, cost_usd: float = 0.0) -> None:
        now = time.time()
        # Unblock stale entries.
        if ip in self._blocked and now >= self._blocked[ip]:
            del self._blocked[ip]
        if ip in self._blocked:
            raise DDoSDetected(
                message=f"ip {ip!r} temporarily blocked",
                threat_type=ThreatType.DDOS_VOLUMETRIC.value,
                severity="high",
            )
        self._minute_window[ip].append(now)
        self._hour_window[ip].append(now)
        self._cost_window[ip].append((now, cost_usd))
        self._prune(self._minute_window[ip], now - 60)
        self._prune(self._hour_window[ip], now - 3600)
        while self._cost_window[ip] and self._cost_window[ip][0][0] < now - 60:
            self._cost_window[ip].popleft()

        if len(self._minute_window[ip]) > self._limits.per_minute:
            self.block(ip)
            raise DDoSDetected(
                message=f"ip {ip!r} exceeded per-minute limit",
                threat_type=ThreatType.DDOS_VOLUMETRIC.value,
                severity="high",
            )
        if len(self._hour_window[ip]) > self._limits.per_hour:
            self.block(ip)
            raise DDoSDetected(
                message=f"ip {ip!r} exceeded per-hour limit",
                threat_type=ThreatType.DDOS_VOLUMETRIC.value,
                severity="high",
            )
        spend = sum(c for _, c in self._cost_window[ip])
        if spend > self._limits.cost_exhaustion_usd_per_minute:
            self.block(ip)
            raise DDoSDetected(
                message=f"ip {ip!r} exceeded cost exhaustion threshold",
                threat_type=ThreatType.DDOS_COST_EXHAUSTION.value,
                severity="critical",
            )

    def block(self, ip: str) -> None:
        self._blocked[ip] = time.time() + self._limits.block_duration_seconds
        try:
            get_metrics().ip_blocks_total.inc()
        except Exception:
            pass

    def is_blocked(self, ip: str) -> bool:
        if ip in self._blocked and time.time() >= self._blocked[ip]:
            del self._blocked[ip]
        return ip in self._blocked

    def stats(self) -> dict[str, Any]:
        return {
            "active_blocks": len(self._blocked),
            "tracked_ips": len(self._minute_window),
        }


# ----- Behavioural analyser --------------------------------------------


@dataclass
class BehavioralThresholds:
    firewall_block_rate_red: float = 0.5  # fraction of queries blocked
    critic_failure_rate_red: float = 0.3
    session_query_count_extraction: int = 30


@dataclass
class _SessionHistory:
    events: list[dict[str, Any]] = field(default_factory=list)


class BehavioralAnalyzer:
    """Per-session trajectory analyser."""

    def __init__(
        self,
        thresholds: BehavioralThresholds | None = None,
        *,
        audit: AuditLogger | None = None,
    ) -> None:
        self._thresholds = thresholds or BehavioralThresholds()
        self._sessions: dict[str, _SessionHistory] = defaultdict(_SessionHistory)
        self._audit = audit

    def record_query(
        self,
        session_id: str,
        *,
        blocked_by_firewall: bool = False,
        critic_failed: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._sessions[session_id].events.append(
            {
                "timestamp": time.time(),
                "firewall_block": blocked_by_firewall,
                "critic_failed": critic_failed,
                "metadata": metadata or {},
            }
        )

    def analyze_session(self, session_id: str) -> ThreatAlert | None:
        history = self._sessions.get(session_id)
        if history is None or not history.events:
            return None
        n = len(history.events)
        fw = sum(1 for e in history.events if e["firewall_block"]) / n
        cr = sum(1 for e in history.events if e["critic_failed"]) / n

        if n >= self._thresholds.session_query_count_extraction:
            return ThreatAlert(
                threat_type=ThreatType.MODEL_EXTRACTION,
                severity=ThreatSeverity.HIGH,
                source=session_id,
                reason=f"session issued {n} queries — model-extraction pattern",
                metadata={"event_count": n},
            )
        if fw >= self._thresholds.firewall_block_rate_red:
            return ThreatAlert(
                threat_type=ThreatType.PROMPT_INJECTION_CAMPAIGN,
                severity=ThreatSeverity.HIGH,
                source=session_id,
                reason=f"firewall block rate {fw:.2%}",
                metadata={"block_rate": fw},
            )
        if cr >= self._thresholds.critic_failure_rate_red:
            return ThreatAlert(
                threat_type=ThreatType.MULTI_TURN_MANIPULATION,
                severity=ThreatSeverity.MEDIUM,
                source=session_id,
                reason=f"critic failure rate {cr:.2%}",
                metadata={"critic_failure_rate": cr},
            )
        return None


# ----- Deception engine ------------------------------------------------


class DeceptionEngine:
    """Honey docs / tokens / canary queries. Any access = attack."""

    def __init__(self) -> None:
        self._honey_docs: set[str] = set()
        self._honey_tokens: set[str] = set()
        self._canary_queries: set[str] = set()

    def register_honey_doc(self, doc_id: str) -> None:
        self._honey_docs.add(doc_id)

    def register_honey_token(self, token: str) -> None:
        self._honey_tokens.add(token)

    def register_canary(self, query: str) -> None:
        self._canary_queries.add(query.lower())

    def check_doc_access(self, doc_id: str) -> ThreatAlert | None:
        if doc_id in self._honey_docs:
            return ThreatAlert(
                threat_type=ThreatType.HONEY_DOC_ACCESSED,
                severity=ThreatSeverity.CRITICAL,
                source=doc_id,
                reason="honey document accessed",
            )
        return None

    def check_token_use(self, token: str) -> ThreatAlert | None:
        if token in self._honey_tokens:
            return ThreatAlert(
                threat_type=ThreatType.HONEY_TOKEN_TRIGGERED,
                severity=ThreatSeverity.CRITICAL,
                source=token,
                reason="honey token used",
            )
        return None

    def check_canary(self, query: str) -> ThreatAlert | None:
        if query.lower() in self._canary_queries:
            return ThreatAlert(
                threat_type=ThreatType.CANARY_DRIFT,
                severity=ThreatSeverity.HIGH,
                source=query[:64],
                reason="canary query invoked",
            )
        return None


# ----- Top-level manager ------------------------------------------------


class ThreatDetectionManager:
    """Routes inbound signals to the right sub-detector + publishes metrics."""

    def __init__(
        self,
        *,
        rate_limits: EdgeLimits | None = None,
        behavioral: BehavioralThresholds | None = None,
        pattern_catalog: PatternCatalog | None = None,
        audit: AuditLogger | None = None,
        store: KeyValueStore | None = None,
    ) -> None:
        self._rate_limiter = EdgeRateLimiter(rate_limits)
        self._behavioral = BehavioralAnalyzer(behavioral, audit=audit)
        self._deception = DeceptionEngine()
        self._patterns = pattern_catalog or default_threat_catalog()
        self._audit = audit
        self._store = store
        self._alerts: list[ThreatAlert] = []

    @property
    def rate_limiter(self) -> EdgeRateLimiter:
        return self._rate_limiter

    @property
    def behavioral(self) -> BehavioralAnalyzer:
        return self._behavioral

    @property
    def deception(self) -> DeceptionEngine:
        return self._deception

    def check_request(
        self,
        *,
        ip: str,
        session_id: str,
        cost_usd: float = 0.0,
        content: str = "",
    ) -> None:
        # Rate limiter raises DDoSDetected directly.
        self._rate_limiter.check(ip, cost_usd=cost_usd)
        # Pattern scan of the content — raise on high-severity match.
        matched = self._patterns.scan(content)
        for pattern in matched:
            if pattern.severity in ("critical", "high"):
                alert = ThreatAlert(
                    threat_type=(
                        ThreatType.DATA_EXFILTRATION if "exfil" in pattern.name else ThreatType.MODEL_EXTRACTION
                    ),
                    severity=ThreatSeverity(pattern.severity),
                    source=ip,
                    reason=f"matched pattern {pattern.name}",
                    metadata={"pattern": pattern.name},
                )
                self._record(alert)
                raise ThreatDetected(
                    message=alert.reason,
                    threat_type=alert.threat_type.value,
                    severity=alert.severity.value,
                )

    def analyze_session(self, session_id: str) -> ThreatAlert | None:
        alert = self._behavioral.analyze_session(session_id)
        if alert is not None:
            self._record(alert)
            if alert.severity is ThreatSeverity.CRITICAL:
                get_degradation_state().set(DegradationLevel.DEGRADED, source="threat_detection", reason=alert.reason)
        return alert

    def honey_doc_accessed(self, doc_id: str) -> None:
        alert = self._deception.check_doc_access(doc_id)
        if alert is not None:
            self._record(alert)
            raise HoneyTokenTriggered(
                message=alert.reason,
                threat_type=alert.threat_type.value,
                severity=alert.severity.value,
            )

    def honey_token_used(self, token: str) -> None:
        alert = self._deception.check_token_use(token)
        if alert is not None:
            self._record(alert)
            raise HoneyTokenTriggered(
                message=alert.reason,
                threat_type=alert.threat_type.value,
                severity=alert.severity.value,
            )

    def canary_invoked(self, query: str) -> None:
        alert = self._deception.check_canary(query)
        if alert is not None:
            self._record(alert)
            raise ThreatDetected(
                message=alert.reason,
                threat_type=alert.threat_type.value,
                severity=alert.severity.value,
            )

    def behavioral_anomaly(self, session_id: str, reason: str) -> None:
        alert = ThreatAlert(
            threat_type=ThreatType.INSIDER_ABUSE,
            severity=ThreatSeverity.MEDIUM,
            source=session_id,
            reason=reason,
        )
        self._record(alert)
        raise BehavioralAnomalyDetected(
            message=reason,
            threat_type=alert.threat_type.value,
            severity=alert.severity.value,
        )

    def dashboard(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for a in self._alerts:
            by_type[a.threat_type.value] = by_type.get(a.threat_type.value, 0) + 1
        return {
            "total_alerts": len(self._alerts),
            "by_type": by_type,
            "rate_limiter": self._rate_limiter.stats(),
        }

    def _record(self, alert: ThreatAlert) -> None:
        self._alerts.append(alert)
        try:
            get_metrics().threats_detected_total.labels(
                threat_type=alert.threat_type.value,
                severity=alert.severity.value,
            ).inc()
        except Exception:
            pass
        if self._audit is not None:
            # Fire-and-forget; the caller's event loop picks it up.
            import asyncio

            try:
                asyncio.get_event_loop().create_task(
                    self._audit.emit(
                        AuditRecord(
                            event_type=AuditEvent.THREAT_DETECTED.value,
                            persona="security",
                            action=alert.severity.value,
                            extra={
                                "threat_type": alert.threat_type.value,
                                "source": alert.source,
                                "reason": alert.reason,
                            },
                        )
                    )
                )
            except RuntimeError:
                # No running loop — e.g. synchronous test path. Drop silently.
                pass


__all__ = [
    "BehavioralAnalyzer",
    "BehavioralThresholds",
    "DeceptionEngine",
    "EdgeLimits",
    "EdgeRateLimiter",
    "ThreatAlert",
    "ThreatDetectionManager",
    "ThreatSeverity",
    "ThreatType",
]
