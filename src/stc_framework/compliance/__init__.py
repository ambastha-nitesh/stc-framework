"""Regulatory compliance engines.

Each submodule focuses on a single regulation or ethical concern:

* :mod:`.rule_2210` — FINRA Rule 2210 communications with the public.
* :mod:`.reg_bi` — Reg BI suitability.
* :mod:`.nydfs_notification` — NYDFS 72-hour breach notification.
* :mod:`.part_500_cert` — NYDFS Part 500 annual certification.
* :mod:`.bias_fairness` — EEOC 4/5ths disparate-impact monitor.
* :mod:`.ip_risk` — Trademark / copyright scanner.
* :mod:`.transparency` — Disclosure + consent.
* :mod:`.privilege_routing` — Attorney-client privilege routing.
* :mod:`.fiduciary` — Cross-tier fairness.
* :mod:`.legal_hold` — Legal hold registry (implements
  :class:`~stc_framework.governance.destruction.LegalHoldChecker`).
* :mod:`.explainability` — Narrative generator over a lineage record.
* :mod:`.sovereignty` — Model origin, inference-jurisdiction, state AI
  law matrix.
"""

from stc_framework.compliance.bias_fairness import (
    ADVERSE_IMPACT_RATIO,
    BiasFairnessMonitor,
    BiasReport,
    FairnessMetric,
)
from stc_framework.compliance.explainability import LegalExplainabilityEngine
from stc_framework.compliance.fiduciary import (
    FairnessCheckResult,
    FiduciaryFairnessChecker,
)
from stc_framework.compliance.ip_risk import IPRiskFlag, IPRiskResult, IPRiskScanner
from stc_framework.compliance.legal_hold import LegalHold, LegalHoldManager
from stc_framework.compliance.nydfs_notification import (
    IncidentNotification,
    NotificationStatus,
    NYDFSNotificationEngine,
)
from stc_framework.compliance.part_500_cert import (
    PART_500_SECTIONS,
    EvidenceItem,
    GapRecord,
    Part500CertificationAssembler,
)
from stc_framework.compliance.patterns import (
    PatternCatalog,
    default_finra_catalog,
    default_ip_catalog,
)
from stc_framework.compliance.privilege_routing import (
    PRIVILEGE_KEYWORDS,
    PrivilegeDecision,
    PrivilegeRouter,
)
from stc_framework.compliance.reg_bi import (
    CustomerProfile,
    RegBICheckpoint,
    SuitabilityCheckResult,
    SuitabilityResult,
)
from stc_framework.compliance.rule_2210 import (
    CommunicationType,
    ContentAnalyzer,
    ContentViolation,
    PrincipalApprovalQueue,
    ReviewDecision,
    ReviewResult,
    Rule2210Engine,
)
from stc_framework.compliance.sovereignty import (
    InferenceEndpoint,
    InferenceJurisdictionEnforcer,
    ModelOriginPolicy,
    ModelOriginProfile,
    OriginRisk,
    QueryPatternProtector,
    StateAILaw,
    StateComplianceMatrix,
)
from stc_framework.compliance.transparency import (
    DEFAULT_DISCLOSURE,
    ConsentRecord,
    TransparencyManager,
)

__all__ = [
    "ADVERSE_IMPACT_RATIO",
    "DEFAULT_DISCLOSURE",
    "PART_500_SECTIONS",
    "PRIVILEGE_KEYWORDS",
    "BiasFairnessMonitor",
    "BiasReport",
    "CommunicationType",
    "ConsentRecord",
    "ContentAnalyzer",
    "ContentViolation",
    "CustomerProfile",
    "EvidenceItem",
    "FairnessCheckResult",
    "FairnessMetric",
    "FiduciaryFairnessChecker",
    "GapRecord",
    "IPRiskFlag",
    "IPRiskResult",
    "IPRiskScanner",
    "IncidentNotification",
    "InferenceEndpoint",
    "InferenceJurisdictionEnforcer",
    "LegalExplainabilityEngine",
    "LegalHold",
    "LegalHoldManager",
    "ModelOriginPolicy",
    "ModelOriginProfile",
    "NYDFSNotificationEngine",
    "NotificationStatus",
    "OriginRisk",
    "Part500CertificationAssembler",
    "PatternCatalog",
    "PrincipalApprovalQueue",
    "PrivilegeDecision",
    "PrivilegeRouter",
    "QueryPatternProtector",
    "RegBICheckpoint",
    "ReviewDecision",
    "ReviewResult",
    "Rule2210Engine",
    "StateAILaw",
    "StateComplianceMatrix",
    "SuitabilityCheckResult",
    "SuitabilityResult",
    "TransparencyManager",
    "default_finra_catalog",
    "default_ip_catalog",
]
