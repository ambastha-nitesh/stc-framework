"""Narrative explainability over a lineage record.

Given a sealed :class:`LineageRecord`, produce a plain-English
explanation of how the response was generated — for regulator review,
customer disclosure, or internal audit. Avoids exposing the raw user
query / response content (that lives in lineage metadata only when
explicitly preserved).
"""

from __future__ import annotations

from stc_framework.governance.lineage import LineageRecord


class LegalExplainabilityEngine:
    """Produces a 7-step narrative from a lineage record."""

    def explain(self, lineage: LineageRecord) -> str:
        lines: list[str] = []
        lines.append(
            f"Request {lineage.lineage_id} was received"
            + (f" from tenant {lineage.tenant_id}" if lineage.tenant_id else "")
            + (f" in session {lineage.session_id}" if lineage.session_id else "")
            + "."
        )
        if lineage.sources:
            ids = ", ".join(s.doc_id for s in lineage.sources[:5])
            more = "" if len(lineage.sources) <= 5 else f" (and {len(lineage.sources) - 5} more)"
            lines.append(f"It was grounded against {len(lineage.sources)} source documents: {ids}{more}.")
        if lineage.embedding is not None:
            lines.append(
                f"Query text was embedded using '{lineage.embedding.embedder_id}' "
                f"(vector size {lineage.embedding.vector_size})."
            )
        if lineage.retrieval is not None:
            lines.append(
                f"The top-{lineage.retrieval.top_k} chunks were retrieved from collection "
                f"'{lineage.retrieval.collection}'."
            )
        if lineage.context is not None:
            lines.append(
                f"{lineage.context.chunk_count} chunks ({lineage.context.total_chars} characters) "
                f"were assembled into the prompt context."
            )
        if lineage.generation is not None:
            lines.append(
                f"Model '{lineage.generation.model_id}' produced the response"
                + (
                    f" using prompt version {lineage.generation.prompt_version}"
                    if lineage.generation.prompt_version
                    else ""
                )
                + "."
            )
        if lineage.validation is not None:
            rail_names = [r.get("name", "?") for r in lineage.validation.rails]
            lines.append(
                f"Output was validated through {len(rail_names)} guardrails "
                f"({', '.join(rail_names) or 'none listed'}); action = {lineage.validation.action}."
            )
        if lineage.response is not None:
            lines.append(
                f"Response delivered (status = {lineage.response.status}; "
                f"{lineage.response.char_count} characters)."
            )
        return "\n".join(lines)


__all__ = ["LegalExplainabilityEngine"]
