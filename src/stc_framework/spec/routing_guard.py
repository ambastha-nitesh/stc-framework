"""Shared predicate for deciding whether a model identifier is in-boundary.

Used by both :mod:`stc_framework.spec.models` (for load-time validation)
and :mod:`stc_framework.sentinel.gateway` (for boundary-crossing audit).
Keeping the rule here means there is exactly one place to update when a
new deployment target is added.
"""

from __future__ import annotations

# Prefixes that identify models which never leave the customer trust
# boundary: local inference servers (Ollama), self-hosted vLLM, and AWS
# Bedrock instances launched inside the customer VPC.
_LOCAL_PREFIXES = (
    "local/",
    "ollama/",
    "vllm/",
    "tgi/",          # HuggingFace Text Generation Inference
    "bedrock/",      # Customer-VPC Bedrock is considered in-boundary
    "sagemaker/",    # Customer-VPC SageMaker
    "vertex-ai-private/",
    "mock/",         # Mock LLM is purely in-process; always in-boundary
)

# Host fragments that also signal in-boundary deployment.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", ".internal", ".vpc.")


def is_local_model(model: str) -> bool:
    """Return True if the model string denotes an in-boundary endpoint."""
    lowered = model.lower()
    if lowered.startswith(_LOCAL_PREFIXES):
        return True
    for host in _LOCAL_HOSTS:
        if host in lowered:
            return True
    return False
