"""Critic: zero-trust governance plane."""

from stc_framework.critic.critic import Critic
from stc_framework.critic.escalation import EscalationManager
from stc_framework.critic.rails import RailRunner
from stc_framework.critic.validators.base import GuardrailResult, GovernanceVerdict

__all__ = [
    "Critic",
    "EscalationManager",
    "GovernanceVerdict",
    "GuardrailResult",
    "RailRunner",
]
