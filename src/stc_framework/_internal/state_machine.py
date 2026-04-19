"""Lightweight state machine helper.

Used by risk register, workflow tasks, regulatory-ops submissions, and any
other lifecycle-bearing record that needs transition logging. Intentionally
tiny: a transitions table + a record base class that captures every change.

Example::

    class RiskState(str, Enum):
        IDENTIFIED = "identified"
        ASSESSED = "assessed"
        CLOSED = "closed"

    TRANSITIONS = {
        RiskState.IDENTIFIED: {RiskState.ASSESSED},
        RiskState.ASSESSED: {RiskState.CLOSED},
        RiskState.CLOSED: set(),
    }

    record = StatefulRecord(state=RiskState.IDENTIFIED)
    record.transition(RiskState.ASSESSED, TRANSITIONS, actor="riskops", reason="...")
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

TState = TypeVar("TState")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Transition(Generic[TState]):
    """A single state change record."""

    from_state: TState
    to_state: TState
    timestamp: str
    actor: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class IllegalTransition(ValueError):
    """Raised when a transition is not declared in the transitions table."""


@dataclass
class StatefulRecord(Generic[TState]):
    """Base container for any record whose lifecycle we track.

    Subclasses add their own domain fields (risk details, task IO, etc.).
    The ``state`` plus ``history`` pair gives auditors a complete
    transition log without each domain reinventing it.
    """

    state: TState
    history: list[Transition[TState]] = field(default_factory=list)

    def transition(
        self,
        new_state: TState,
        transitions: Mapping[TState, set[TState]],
        *,
        actor: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> Transition[TState]:
        """Move to ``new_state`` if the transition is permitted.

        Appends a :class:`Transition` to ``history`` and updates ``state``.
        Raises :class:`IllegalTransition` if the move is not in the
        declared transitions map.
        """
        allowed = transitions.get(self.state, set())
        if new_state not in allowed:
            raise IllegalTransition(
                f"cannot transition from {self.state!r} to {new_state!r}; " f"allowed={sorted(str(s) for s in allowed)}"
            )
        entry = Transition(
            from_state=self.state,
            to_state=new_state,
            timestamp=_utc_now(),
            actor=actor,
            reason=reason,
            metadata=dict(metadata or {}),
        )
        self.history.append(entry)
        self.state = new_state
        return entry

    def can_transition(
        self,
        new_state: TState,
        transitions: Mapping[TState, set[TState]],
    ) -> bool:
        """Return True if the transition would be permitted."""
        return new_state in transitions.get(self.state, set())


__all__ = ["IllegalTransition", "StatefulRecord", "Transition"]
