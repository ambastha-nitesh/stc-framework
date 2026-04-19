"""External guardrail service adapters (NeMo, Guardrails AI).

Critic validators live in :mod:`stc_framework.critic.validators` — these
adapters wrap **external** guardrail services, used only when the spec
references them and the corresponding extra is installed.
"""

from stc_framework.adapters.guardrails.base import (
    ExternalGuardrailClient,
    GuardrailCheck,
)

__all__ = ["ExternalGuardrailClient", "GuardrailCheck"]
