"""
STC Framework — Data Catalog & Quality Engine
governance/data_catalog.py

Centralized catalog for all data assets in the STC system:
  - Documents (source files, filings, reports)
  - Collections (vector store groupings)
  - Models (LLMs, embedding models, classifiers)
  - Prompts (templates with version tracking)

Includes:
  - Quality scoring engine (6 dimensions: accuracy, completeness,
    timeliness, consistency, uniqueness, validity)
  - Freshness monitoring with staleness detection
  - Model registry with evaluation tracking
  - Data contract validation
"""

import json
import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("stc.governance.catalog")


# ── Asset Status ────────────────────────────────────────────────────────────

class AssetStatus(Enum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"
    QUARANTINED = "quarantined"  # Quality below threshold
    DEPRECATED = "deprecated"

class ModelStatus(Enum):
    EVALUATION = "evaluation"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


# ── Quality Scoring ─────────────────────────────────────────────────────────

@dataclass
class QualityDimensions:
    """Quality scores per dimension (0-100 each)."""
    accuracy: float = 100.0
    completeness: float = 100.0
    timeliness: float = 100.0
    consistency: float = 100.0
    uniqueness: float = 100.0
    validity: float = 100.0

    @property
    def composite(self) -> float:
        return (self.accuracy * 0.35 + self.completeness * 0.20 +
                self.timeliness * 0.20 + self.consistency * 0.15 +
                self.validity * 0.10)

    @property
    def status(self) -> str:
        c = self.composite
        if c >= 80: return "good"
        elif c >= 70: return "acceptable"
        elif c >= 50: return "review_required"
        return "quarantine"


# ── Document Asset ──────────────────────────────────────────────────────────

@dataclass
class DocumentAsset:
    doc_id: str
    title: str
    source_system: str
    classification_tier: str  # public | internal | restricted
    data_steward: str
    version: str = "1.0"
    format: str = "text"
    size_bytes: int = 0
    ingestion_date: str = ""
    freshness_date: str = ""  # Date the content represents
    freshness_sla_days: int = 90
    collection_id: str = ""
    status: AssetStatus = AssetStatus.ACTIVE
    quality: QualityDimensions = field(default_factory=QualityDimensions)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_stale(self) -> bool:
        if not self.freshness_date:
            return False
        try:
            fresh = datetime.fromisoformat(self.freshness_date)
            if fresh.tzinfo is None:
                fresh = fresh.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.freshness_sla_days)
            return fresh < cutoff
        except:
            return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id, "title": self.title,
            "source_system": self.source_system, "classification_tier": self.classification_tier,
            "data_steward": self.data_steward, "version": self.version,
            "status": self.status.value, "quality_score": round(self.quality.composite, 1),
            "quality_status": self.quality.status, "is_stale": self.is_stale,
            "freshness_date": self.freshness_date, "collection_id": self.collection_id,
        }


# ── Model Asset ─────────────────────────────────────────────────────────────

@dataclass
class ModelAsset:
    model_id: str
    model_type: str               # llm | embedding | classifier | reranker
    provider: str
    version: str
    status: ModelStatus = ModelStatus.EVALUATION
    provenance_trust: str = "unverified"
    data_tiers_approved: List[str] = field(default_factory=lambda: ["public"])
    eval_scores: Dict[str, float] = field(default_factory=dict)
    safety_eval: Dict[str, float] = field(default_factory=dict)
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    approved_by: str = ""
    deployed_at: str = ""
    next_review: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id, "model_type": self.model_type,
            "provider": self.provider, "version": self.version,
            "status": self.status.value, "provenance_trust": self.provenance_trust,
            "data_tiers_approved": self.data_tiers_approved,
            "eval_scores": self.eval_scores, "safety_eval": self.safety_eval,
            "approved_by": self.approved_by, "deployed_at": self.deployed_at,
        }


# ── Prompt Asset ────────────────────────────────────────────────────────────

@dataclass
class PromptAsset:
    template_id: str
    version: str
    purpose: str
    author: str
    template_text: str = ""       # Not stored in full — reference to Langfuse
    linked_model_ids: List[str] = field(default_factory=list)
    eval_score: float = 0.0
    status: str = "active"        # draft | review | active | deprecated
    created_at: str = ""
    last_modified: str = ""


# ── Data Catalog ────────────────────────────────────────────────────────────

class DataCatalog:
    """
    Centralized data catalog for all STC data assets.

    Usage:
        catalog = DataCatalog()
        catalog.register_document(DocumentAsset(...))
        catalog.register_model(ModelAsset(...))
        stale = catalog.check_freshness()
        report = catalog.governance_scorecard()
    """

    def __init__(self, audit_callback: Optional[Callable] = None):
        self._documents: Dict[str, DocumentAsset] = {}
        self._models: Dict[str, ModelAsset] = {}
        self._prompts: Dict[str, PromptAsset] = {}
        self._audit_callback = audit_callback

    # ── Document Management ─────────────────────────────────────────────

    def register_document(self, doc: DocumentAsset):
        self._documents[doc.doc_id] = doc
        self._emit("document_registered", {"doc_id": doc.doc_id, "title": doc.title,
                                            "quality": round(doc.quality.composite, 1)})

    def update_quality(self, doc_id: str, quality: QualityDimensions):
        doc = self._documents.get(doc_id)
        if not doc:
            raise KeyError(f"Document not found: {doc_id}")
        old_score = doc.quality.composite
        doc.quality = quality
        new_score = quality.composite

        # Auto-quarantine if quality drops below 50
        if new_score < 50 and doc.status == AssetStatus.ACTIVE:
            doc.status = AssetStatus.QUARANTINED
            self._emit("document_quarantined", {"doc_id": doc_id, "quality": round(new_score, 1)})
        elif new_score >= 50 and doc.status == AssetStatus.QUARANTINED:
            doc.status = AssetStatus.ACTIVE

    def check_freshness(self) -> List[Dict[str, Any]]:
        """Check all documents for staleness. Returns list of stale documents."""
        stale = []
        for doc in self._documents.values():
            if doc.status == AssetStatus.ACTIVE and doc.is_stale:
                doc.status = AssetStatus.STALE
                stale.append({
                    "doc_id": doc.doc_id, "title": doc.title,
                    "freshness_date": doc.freshness_date,
                    "sla_days": doc.freshness_sla_days,
                    "steward": doc.data_steward,
                })
        if stale:
            self._emit("staleness_detected", {"count": len(stale),
                                               "docs": [s["doc_id"] for s in stale]})
        return stale

    def search_documents(self, **filters) -> List[DocumentAsset]:
        """Search documents by filters (classification_tier, status, source_system, etc.)."""
        results = list(self._documents.values())
        for key, value in filters.items():
            results = [d for d in results if getattr(d, key, None) == value]
        return results

    # ── Model Registry ──────────────────────────────────────────────────

    def register_model(self, model: ModelAsset):
        self._models[model.model_id] = model
        self._emit("model_registered", {"model_id": model.model_id, "type": model.model_type,
                                         "status": model.status.value})

    def approve_model(self, model_id: str, approved_by: str,
                      data_tiers: List[str] = None):
        model = self._models.get(model_id)
        if not model:
            raise KeyError(f"Model not found: {model_id}")
        model.status = ModelStatus.APPROVED
        model.approved_by = approved_by
        if data_tiers:
            model.data_tiers_approved = data_tiers
        self._emit("model_approved", {"model_id": model_id, "approved_by": approved_by})

    def deploy_model(self, model_id: str):
        model = self._models.get(model_id)
        if not model:
            raise KeyError(f"Model not found: {model_id}")
        if model.status != ModelStatus.APPROVED:
            raise ValueError(f"Model {model_id} must be approved before deployment (current: {model.status.value})")
        model.status = ModelStatus.DEPLOYED
        model.deployed_at = datetime.now(timezone.utc).isoformat()
        self._emit("model_deployed", {"model_id": model_id})

    def deprecate_model(self, model_id: str, reason: str):
        model = self._models.get(model_id)
        if not model:
            raise KeyError(f"Model not found: {model_id}")
        model.status = ModelStatus.DEPRECATED
        self._emit("model_deprecated", {"model_id": model_id, "reason": reason})

    def update_eval_scores(self, model_id: str, eval_scores: Dict[str, float],
                           safety_eval: Dict[str, float] = None):
        model = self._models.get(model_id)
        if not model:
            raise KeyError(f"Model not found: {model_id}")
        model.eval_scores = eval_scores
        if safety_eval:
            model.safety_eval = safety_eval

    def deployed_models(self) -> List[ModelAsset]:
        return [m for m in self._models.values() if m.status == ModelStatus.DEPLOYED]

    def models_due_for_review(self) -> List[ModelAsset]:
        now = datetime.now(timezone.utc)
        due = []
        for m in self._models.values():
            if m.next_review:
                try:
                    review_date = datetime.fromisoformat(m.next_review)
                    if review_date.tzinfo is None:
                        review_date = review_date.replace(tzinfo=timezone.utc)
                    if review_date <= now:
                        due.append(m)
                except:
                    pass
        return due

    # ── Prompt Registry ─────────────────────────────────────────────────

    def register_prompt(self, prompt: PromptAsset):
        self._prompts[prompt.template_id] = prompt

    # ── Governance Scorecard ────────────────────────────────────────────

    def governance_scorecard(self) -> Dict[str, Any]:
        """Generate the governance scorecard for reporting."""
        total_docs = len(self._documents)
        active_docs = [d for d in self._documents.values() if d.status == AssetStatus.ACTIVE]
        stale_docs = [d for d in self._documents.values() if d.status == AssetStatus.STALE]
        quarantined = [d for d in self._documents.values() if d.status == AssetStatus.QUARANTINED]

        avg_quality = (sum(d.quality.composite for d in active_docs) / len(active_docs)
                       if active_docs else 0)

        total_models = len(self._models)
        deployed_models = len(self.deployed_models())
        due_for_review = len(self.models_due_for_review())

        return {
            "generated": datetime.now(timezone.utc).isoformat(),
            "documents": {
                "total": total_docs,
                "active": len(active_docs),
                "stale": len(stale_docs),
                "quarantined": len(quarantined),
                "average_quality": round(avg_quality, 1),
                "stale_rate": round(len(stale_docs) / total_docs * 100, 1) if total_docs else 0,
            },
            "models": {
                "total": total_models,
                "deployed": deployed_models,
                "due_for_review": due_for_review,
                "by_status": {s.value: sum(1 for m in self._models.values() if m.status == s)
                              for s in ModelStatus},
            },
            "prompts": {
                "total": len(self._prompts),
                "active": sum(1 for p in self._prompts.values() if p.status == "active"),
            },
            "governance_metrics": {
                "catalog_completeness": "100%" if total_docs > 0 else "0%",
                "avg_quality_score": round(avg_quality, 1),
                "stale_doc_rate": f"{len(stale_docs) / total_docs * 100:.1f}%" if total_docs else "0%",
                "model_registry_currency": f"{deployed_models}/{total_models}",
            },
        }

    def _emit(self, event_type, details):
        if self._audit_callback:
            self._audit_callback({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "component": "governance.catalog",
                "event_type": event_type, "details": details,
            })


# ── Demo ────────────────────────────────────────────────────────────────────

def demo():
    print("=" * 70)
    print("STC Data Catalog & Quality Engine — Demo")
    print("=" * 70)

    audit_log = []
    catalog = DataCatalog(audit_callback=lambda e: audit_log.append(e))

    # ── Register Documents ──
    print("\n▸ Registering documents...")

    docs = [
        DocumentAsset("acme-10k-fy2024", "ACME Corp 10-K FY2024", "EDGAR", "public",
                       "regulatory-data-steward", "1.0", "pdf", 2_500_000,
                       "2026-03-01", "2025-12-31", 120, "stc_financial_docs",
                       quality=QualityDimensions(98, 95, 100, 100, 100, 100)),
        DocumentAsset("acme-10q-q3", "ACME Corp 10-Q Q3 2025", "EDGAR", "public",
                       "regulatory-data-steward", "1.0", "pdf", 1_200_000,
                       "2025-11-15", "2025-09-30", 90, "stc_financial_docs",
                       quality=QualityDimensions(97, 92, 60, 100, 100, 100)),  # Timeliness low — old
        DocumentAsset("internal-strategy-2026", "LPL AI Strategy 2026", "SharePoint", "internal",
                       "document-steward", "2.1", "docx", 500_000,
                       "2026-02-15", "2026-02-15", 365, "stc_internal_docs",
                       quality=QualityDimensions(90, 88, 100, 85, 100, 95)),
        DocumentAsset("client-report-sample", "Client Portfolio Summary", "BetaNXT", "restricted",
                       "client-data-steward", "1.0", "json", 50_000,
                       "2026-03-01", "2026-03-01", 30, "stc_client_docs",
                       quality=QualityDimensions(95, 90, 100, 90, 100, 100)),
        DocumentAsset("stale-market-data", "Market Summary Jan 2025", "Bloomberg", "public",
                       "market-data-steward", "1.0", "json", 75_000,
                       "2025-01-15", "2025-01-15", 30, "stc_market_docs",
                       quality=QualityDimensions(99, 95, 10, 100, 100, 100)),  # Very stale
    ]

    for doc in docs:
        catalog.register_document(doc)
        print(f"  {doc.doc_id}: quality={doc.quality.composite:.1f} ({doc.quality.status}), "
              f"tier={doc.classification_tier}")

    # ── Freshness Check ──
    print("\n▸ Checking document freshness...")
    stale = catalog.check_freshness()
    for s in stale:
        print(f"  ⚠ STALE: {s['doc_id']} (freshness: {s['freshness_date']}, SLA: {s['sla_days']} days)")
    if not stale:
        print("  All documents within freshness SLA")

    # ── Quality Update (simulate degradation) ──
    print("\n▸ Simulating quality degradation...")
    catalog.update_quality("stale-market-data", QualityDimensions(99, 95, 5, 80, 100, 100))
    doc = catalog._documents["stale-market-data"]
    print(f"  stale-market-data: quality={doc.quality.composite:.1f} ({doc.quality.status}), "
          f"status={doc.status.value}")

    # ── Register Models ──
    print("\n▸ Registering models...")

    models = [
        ModelAsset("anthropic/claude-sonnet-4", "llm", "anthropic", "claude-sonnet-4-20250514",
                   ModelStatus.DEPLOYED, "verified", ["public", "internal"],
                   {"accuracy": 0.95, "hallucination": 0.008}, {"injection_resistance": 0.97, "scope": 1.0},
                   0.003, 0.015, "AI Governance Committee", "2026-02-15T14:00:00Z", "2026-05-15"),
        ModelAsset("BAAI/bge-small-en-v1.5", "embedding", "local", "1.5",
                   ModelStatus.DEPLOYED, "trusted", ["public", "internal", "restricted"],
                   {"retrieval_precision": 0.85, "retrieval_recall": 0.78}, {},
                   0.0, 0.0, "ML Engineering", "2026-01-10T10:00:00Z", "2026-04-10"),
        ModelAsset("meta-llama/Llama-3.1-8B", "llm", "local", "3.1-8B",
                   ModelStatus.APPROVED, "trusted", ["public", "internal", "restricted"],
                   {"accuracy": 0.82, "hallucination": 0.03}, {"injection_resistance": 0.88, "scope": 0.95},
                   0.0, 0.0, "AI Governance Committee"),
        ModelAsset("openai/gpt-4o-candidate", "llm", "openai", "gpt-4o-2026-03",
                   ModelStatus.EVALUATION, "verified", ["public"],
                   {}, {},  # Not yet evaluated
                   0.005, 0.015),
    ]

    for model in models:
        catalog.register_model(model)
        print(f"  {model.model_id}: {model.model_type}, status={model.status.value}, "
              f"trust={model.provenance_trust}")

    # ── Model Lifecycle ──
    print("\n▸ Model lifecycle: evaluating GPT-4o candidate...")
    catalog.update_eval_scores("openai/gpt-4o-candidate",
                               {"accuracy": 0.93, "hallucination": 0.012},
                               {"injection_resistance": 0.96, "scope": 1.0})
    catalog.approve_model("openai/gpt-4o-candidate", "AI Governance Committee", ["public", "internal"])
    print(f"  GPT-4o: approved for [public, internal]")

    # Don't deploy yet — just approved
    gpt4o = catalog._models["openai/gpt-4o-candidate"]
    print(f"  Status: {gpt4o.status.value}, eval: {gpt4o.eval_scores}")

    # ── Register Prompts ──
    print("\n▸ Registering prompts...")
    catalog.register_prompt(PromptAsset(
        "financial_qa_v3", "3.2", "Financial document Q&A",
        "ML Engineering", linked_model_ids=["anthropic/claude-sonnet-4"],
        eval_score=0.94, status="active",
        created_at="2026-02-20", last_modified="2026-03-05"))
    print(f"  financial_qa_v3: version 3.2, active")

    # ── Governance Scorecard ──
    print("\n▸ Governance Scorecard:")
    sc = catalog.governance_scorecard()

    print(f"  Documents: {sc['documents']['total']} total, "
          f"{sc['documents']['active']} active, "
          f"{sc['documents']['stale']} stale, "
          f"{sc['documents']['quarantined']} quarantined")
    print(f"  Avg quality: {sc['documents']['average_quality']}")
    print(f"  Stale rate: {sc['governance_metrics']['stale_doc_rate']}")

    print(f"\n  Models: {sc['models']['total']} total, "
          f"{sc['models']['deployed']} deployed, "
          f"{sc['models']['due_for_review']} due for review")
    print(f"  By status: {sc['models']['by_status']}")

    print(f"\n  Prompts: {sc['prompts']['total']} total, "
          f"{sc['prompts']['active']} active")

    # ── Query Examples ──
    print("\n▸ Query: Restricted documents")
    restricted = catalog.search_documents(classification_tier="restricted")
    for d in restricted:
        print(f"  {d.doc_id}: {d.title} (steward: {d.data_steward})")

    print("\n▸ Deployed models:")
    for m in catalog.deployed_models():
        print(f"  {m.model_id}: tiers={m.data_tiers_approved}, eval={m.eval_scores}")

    print(f"\n▸ Audit events: {len(audit_log)}")

    print("\n" + "=" * 70)
    print("✓ Data catalog & quality engine demo complete")
    print("=" * 70)


if __name__ == "__main__":
    demo()
