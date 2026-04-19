"""Data catalog — asset inventory and quality tracking.

Tracks three kinds of assets that flow through an STC deployment:

* **Documents** — source files, filings, reports fed into the vector store.
* **Models** — LLMs, embedders, classifiers with lifecycle state.
* **Prompts** — template versions with active pointer.

Each asset carries a :class:`QualityDimensions` score (six weighted
dimensions) and a status (``ACTIVE`` / ``STALE`` / ``ARCHIVED`` /
``QUARANTINED`` / ``DEPRECATED``). Quality drops below the configured
threshold ⇒ automatic quarantine; freshness SLA elapses ⇒ automatic
``STALE``. Every state change emits an audit event.

Storage is pluggable: every registry goes through
:class:`~stc_framework.infrastructure.store.KeyValueStore`, so a
multi-process deployment swaps in Redis without touching this module.

Example::

    catalog = DataCatalog(store=InMemoryStore(), audit=my_audit_logger)
    await catalog.register_document("doc-1", metadata={"source": "10-K"})
    await catalog.update_quality("doc-1", QualityDimensions(accuracy=0.7, ...))
    await catalog.sweep_freshness()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from stc_framework._internal.metrics_safe import safe_set
from stc_framework._internal.scoring import dimension_score
from stc_framework._internal.ttl import is_stale
from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord
from stc_framework.observability.metrics import get_metrics


class AssetStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"
    QUARANTINED = "quarantined"
    DEPRECATED = "deprecated"


class ModelStatus(str, Enum):
    EVALUATION = "evaluation"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


# Weights sum to 1.0 — documented so audit/compliance can cross-check.
# Accuracy dominates because in financial Q&A, a wrong answer is worse
# than an incomplete one; consistency weights low because measurement
# is noisy. Tweak via spec if your domain disagrees.
QUALITY_WEIGHTS: dict[str, float] = {
    "accuracy": 0.35,
    "completeness": 0.20,
    "timeliness": 0.15,
    "consistency": 0.10,
    "uniqueness": 0.10,
    "validity": 0.10,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class QualityDimensions:
    """Six-dimension data-quality score, each in ``[0.0, 1.0]``."""

    accuracy: float = 1.0
    completeness: float = 1.0
    timeliness: float = 1.0
    consistency: float = 1.0
    uniqueness: float = 1.0
    validity: float = 1.0

    def as_mapping(self) -> dict[str, float]:
        return {
            "accuracy": self.accuracy,
            "completeness": self.completeness,
            "timeliness": self.timeliness,
            "consistency": self.consistency,
            "uniqueness": self.uniqueness,
            "validity": self.validity,
        }

    @property
    def composite(self) -> float:
        return dimension_score(self.as_mapping(), QUALITY_WEIGHTS)


@dataclass
class DocumentAsset:
    asset_id: str
    status: AssetStatus = AssetStatus.ACTIVE
    quality: QualityDimensions = field(default_factory=QualityDimensions)
    registered_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    freshness_sla_seconds: float = 30 * 24 * 3600  # 30 days
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelAsset:
    asset_id: str
    status: ModelStatus = ModelStatus.EVALUATION
    registered_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptAsset:
    asset_id: str
    version: str
    active: bool = False
    registered_at: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


_KEY_DOC = "catalog:doc:{asset_id}"
_KEY_MODEL = "catalog:model:{asset_id}"
_KEY_PROMPT = "catalog:prompt:{asset_id}:{version}"


class DataCatalog:
    """Central registry for documents, models, and prompts.

    All state lives behind a :class:`KeyValueStore`; this class only
    layers domain semantics (quality scoring, lifecycle transitions,
    freshness sweeps) on top.
    """

    def __init__(
        self,
        store: KeyValueStore,
        *,
        audit: AuditLogger | None = None,
        quarantine_threshold: float = 0.50,
    ) -> None:
        self._store = store
        self._audit = audit
        self._quarantine_threshold = quarantine_threshold

    # ----- documents ----------------------------------------------------

    async def register_document(
        self,
        asset_id: str,
        *,
        metadata: dict[str, Any] | None = None,
        freshness_sla_seconds: float | None = None,
    ) -> DocumentAsset:
        asset = DocumentAsset(
            asset_id=asset_id,
            metadata=dict(metadata or {}),
        )
        if freshness_sla_seconds is not None:
            asset.freshness_sla_seconds = freshness_sla_seconds
        await self._store.set(_KEY_DOC.format(asset_id=asset_id), asdict_safe(asset))
        await self._emit(
            AuditEvent.ASSET_REGISTERED,
            extra={"asset_id": asset_id, "asset_type": "document"},
        )
        self._publish_quality_metric("document", asset.quality.composite)
        return asset

    async def get_document(self, asset_id: str) -> DocumentAsset | None:
        raw = await self._store.get(_KEY_DOC.format(asset_id=asset_id))
        return _document_from_dict(raw) if raw else None

    async def update_quality(self, asset_id: str, quality: QualityDimensions) -> DocumentAsset:
        existing = await self.get_document(asset_id)
        if existing is None:
            raise KeyError(f"document not registered: {asset_id!r}")
        existing.quality = quality
        existing.updated_at = _utc_now()
        if quality.composite < self._quarantine_threshold and existing.status != AssetStatus.QUARANTINED:
            existing.status = AssetStatus.QUARANTINED
            await self._emit(
                AuditEvent.ASSET_QUARANTINED,
                extra={
                    "asset_id": asset_id,
                    "asset_type": "document",
                    "composite_quality": round(quality.composite, 4),
                },
            )
        await self._store.set(_KEY_DOC.format(asset_id=asset_id), asdict_safe(existing))
        self._publish_quality_metric("document", quality.composite)
        return existing

    async def deprecate_document(self, asset_id: str, *, reason: str = "") -> DocumentAsset:
        existing = await self.get_document(asset_id)
        if existing is None:
            raise KeyError(f"document not registered: {asset_id!r}")
        existing.status = AssetStatus.DEPRECATED
        existing.updated_at = _utc_now()
        await self._store.set(_KEY_DOC.format(asset_id=asset_id), asdict_safe(existing))
        await self._emit(
            AuditEvent.ASSET_DEPRECATED,
            extra={"asset_id": asset_id, "asset_type": "document", "reason": reason},
        )
        return existing

    # ----- freshness sweep ----------------------------------------------

    async def sweep_freshness(self) -> int:
        """Scan every registered document and mark ``STALE`` if past SLA.

        Emits a ``freshness_violation`` event per newly stale asset.
        Returns the number of documents transitioned.
        """
        transitioned = 0
        keys = await self._store.keys("catalog:doc:*")
        for key in keys:
            raw = await self._store.get(key)
            if not raw:
                continue
            asset = _document_from_dict(raw)
            if asset.status != AssetStatus.ACTIVE:
                continue
            if is_stale(asset.updated_at, max_age_seconds=asset.freshness_sla_seconds):
                asset.status = AssetStatus.STALE
                await self._store.set(key, asdict_safe(asset))
                transitioned += 1
                await self._emit(
                    AuditEvent.FRESHNESS_VIOLATION,
                    extra={"asset_id": asset.asset_id, "asset_type": "document"},
                )
        return transitioned

    # ----- models -------------------------------------------------------

    async def register_model(
        self,
        asset_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ModelAsset:
        asset = ModelAsset(asset_id=asset_id, metadata=dict(metadata or {}))
        await self._store.set(_KEY_MODEL.format(asset_id=asset_id), asdict_safe(asset))
        await self._emit(
            AuditEvent.ASSET_REGISTERED,
            extra={"asset_id": asset_id, "asset_type": "model"},
        )
        return asset

    async def transition_model(self, asset_id: str, new_status: ModelStatus) -> ModelAsset:
        raw = await self._store.get(_KEY_MODEL.format(asset_id=asset_id))
        if not raw:
            raise KeyError(f"model not registered: {asset_id!r}")
        existing = _model_from_dict(raw)
        existing.status = new_status
        existing.updated_at = _utc_now()
        await self._store.set(_KEY_MODEL.format(asset_id=asset_id), asdict_safe(existing))
        if new_status in (ModelStatus.DEPRECATED, ModelStatus.RETIRED):
            await self._emit(
                AuditEvent.ASSET_DEPRECATED,
                extra={"asset_id": asset_id, "asset_type": "model", "status": new_status.value},
            )
        return existing

    # ----- prompts ------------------------------------------------------

    async def register_prompt(
        self,
        asset_id: str,
        version: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> PromptAsset:
        asset = PromptAsset(asset_id=asset_id, version=version, metadata=dict(metadata or {}))
        await self._store.set(_KEY_PROMPT.format(asset_id=asset_id, version=version), asdict_safe(asset))
        await self._emit(
            AuditEvent.ASSET_REGISTERED,
            extra={"asset_id": asset_id, "asset_type": "prompt", "version": version},
        )
        return asset

    async def set_active_prompt(self, asset_id: str, version: str) -> None:
        """Flip the active flag for a specific version; unsets other versions."""
        versions = await self._store.keys(f"catalog:prompt:{asset_id}:*")
        for key in versions:
            raw = await self._store.get(key)
            if not raw:
                continue
            asset = _prompt_from_dict(raw)
            asset.active = asset.version == version
            await self._store.set(key, asdict_safe(asset))

    # ----- reporting ----------------------------------------------------

    async def governance_scorecard(self) -> dict[str, Any]:
        """One-shot dashboard for operators — counts by status + avg quality."""
        by_doc_status: dict[str, int] = {}
        quality_sum = 0.0
        quality_count = 0
        for key in await self._store.keys("catalog:doc:*"):
            raw = await self._store.get(key)
            if not raw:
                continue
            doc = _document_from_dict(raw)
            by_doc_status[doc.status.value] = by_doc_status.get(doc.status.value, 0) + 1
            quality_sum += doc.quality.composite
            quality_count += 1
        by_model_status: dict[str, int] = {}
        for key in await self._store.keys("catalog:model:*"):
            raw = await self._store.get(key)
            if not raw:
                continue
            model = _model_from_dict(raw)
            by_model_status[model.status.value] = by_model_status.get(model.status.value, 0) + 1
        return {
            "documents_by_status": by_doc_status,
            "models_by_status": by_model_status,
            "avg_document_quality": (quality_sum / quality_count) if quality_count else None,
            "asset_counts": {"documents": quality_count, "models": sum(by_model_status.values())},
        }

    # ----- internals ----------------------------------------------------

    async def _emit(self, event: AuditEvent, *, extra: dict[str, Any]) -> None:
        if self._audit is None:
            return
        record = AuditRecord(
            timestamp=_utc_now(),
            event_type=event.value,
            persona="governance",
            extra=extra,
        )
        await self._audit.emit(record)

    def _publish_quality_metric(self, asset_type: str, composite: float) -> None:
        safe_set(get_metrics().asset_quality_score, composite, asset_type=asset_type)


# ----- serialisation helpers --------------------------------------------


def asdict_safe(obj: DocumentAsset | ModelAsset | PromptAsset | QualityDimensions) -> dict[str, Any]:
    """Convert a known catalog dataclass (+ embedded enums) to a dict for the store.

    Only the four catalog dataclasses are accepted — the v0.3.0 staff
    review R6 finding removed the generic ``Any`` signature + unreachable
    fallback branch.
    """
    result = _asdict_recursive(obj)
    # Every catalog dataclass serialises to a dict; the recursive walker
    # guarantees this by construction.
    assert isinstance(result, dict), "catalog dataclass did not serialise to a dict"
    return result


def _asdict_recursive(obj: Any) -> Any:
    if isinstance(obj, (DocumentAsset, ModelAsset, PromptAsset, QualityDimensions)):
        data = {}
        for k, v in vars(obj).items():
            data[k] = _asdict_recursive(v)
        return data
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _asdict_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_asdict_recursive(v) for v in obj]
    return obj


def _document_from_dict(raw: dict[str, Any]) -> DocumentAsset:
    quality_raw = raw.get("quality", {})
    quality = QualityDimensions(**quality_raw) if isinstance(quality_raw, dict) else QualityDimensions()
    return DocumentAsset(
        asset_id=raw["asset_id"],
        status=AssetStatus(raw.get("status", AssetStatus.ACTIVE.value)),
        quality=quality,
        registered_at=raw.get("registered_at", _utc_now()),
        updated_at=raw.get("updated_at", _utc_now()),
        freshness_sla_seconds=float(raw.get("freshness_sla_seconds", 30 * 24 * 3600)),
        metadata=dict(raw.get("metadata", {})),
    )


def _model_from_dict(raw: dict[str, Any]) -> ModelAsset:
    return ModelAsset(
        asset_id=raw["asset_id"],
        status=ModelStatus(raw.get("status", ModelStatus.EVALUATION.value)),
        registered_at=raw.get("registered_at", _utc_now()),
        updated_at=raw.get("updated_at", _utc_now()),
        metadata=dict(raw.get("metadata", {})),
    )


def _prompt_from_dict(raw: dict[str, Any]) -> PromptAsset:
    return PromptAsset(
        asset_id=raw["asset_id"],
        version=raw["version"],
        active=bool(raw.get("active", False)),
        registered_at=raw.get("registered_at", _utc_now()),
        metadata=dict(raw.get("metadata", {})),
    )


__all__ = [
    "QUALITY_WEIGHTS",
    "AssetStatus",
    "DataCatalog",
    "DocumentAsset",
    "ModelAsset",
    "ModelStatus",
    "PromptAsset",
    "QualityDimensions",
]
