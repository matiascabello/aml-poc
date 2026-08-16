"""Alert state machine: pending -> analyzed -> approved -> executed,
with `rejected` as the terminal alternative to `approved`.

This module owns the states, the legal transitions between them, and the
audit log. It has no knowledge of the LLM or the UI — it is pure control
flow, which is the point: it must be provable correct on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

RECOMMENDATIONS = ("escalate", "dismiss")


class AlertState(Enum):
    PENDING = "pending"
    ANALYZED = "analyzed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class InvalidTransitionError(Exception):
    """Raised when code attempts a transition the state machine does not allow."""


# The single source of truth for legal transitions. `rejected` and
# `executed` map to an empty set: both are terminal, nothing leaves them.
ALLOWED_TRANSITIONS: dict[AlertState, set[AlertState]] = {
    AlertState.PENDING: {AlertState.ANALYZED},
    AlertState.ANALYZED: {AlertState.APPROVED, AlertState.REJECTED},
    AlertState.APPROVED: {AlertState.EXECUTED},
    AlertState.REJECTED: set(),
    AlertState.EXECUTED: set(),
}


@dataclass(frozen=True)
class AuditEntry:
    timestamp: datetime
    from_state: AlertState | None
    to_state: AlertState
    detail: str | None = None


@dataclass
class TriageAlert:
    """In-memory record of one alert's progress through the workflow.

    Holds only workflow state (state, recommendation, audit log) — the
    alert evidence (KYC/transactions) and the narrative live in the data
    layer / analyzer output added in later steps, not here.
    """

    alert_id: str
    state: AlertState = field(default=AlertState.PENDING, init=False)
    recommendation: str | None = field(default=None, init=False)
    audit_log: list[AuditEntry] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._record(from_state=None, to_state=AlertState.PENDING, detail="alert created")

    def mark_analyzed(self, recommendation: str) -> None:
        """Attach the analyzer's recommendation and move to `analyzed`."""
        if recommendation not in RECOMMENDATIONS:
            raise ValueError(
                f"recommendation must be one of {RECOMMENDATIONS}, got {recommendation!r}"
            )
        self._transition(AlertState.ANALYZED, detail=f"recommendation={recommendation}")
        self.recommendation = recommendation

    def approve(self) -> None:
        self._transition(AlertState.APPROVED, detail="approved by analyst")

    def reject(self, reason: str | None = None) -> None:
        self._transition(AlertState.REJECTED, detail=reason or "rejected by analyst")

    def _transition(self, to_state: AlertState, detail: str | None = None) -> None:
        """The sole state mutator. Deliberately not exposed as a public
        `mark_executed()`-style wrapper for the executed state: the only
        sanctioned path to `executed` is execute() in execute.py, which
        calls this directly, after — and only after — ensure_approved()
        passes. There is no public primitive on this class that reaches
        `executed` on its own.
        """
        allowed = ALLOWED_TRANSITIONS[self.state]
        if to_state not in allowed:
            raise InvalidTransitionError(
                f"Alert {self.alert_id}: cannot transition from "
                f"{self.state.value!r} to {to_state.value!r}"
            )
        from_state = self.state
        self.state = to_state
        self._record(from_state=from_state, to_state=to_state, detail=detail)

    def _record(
        self, from_state: AlertState | None, to_state: AlertState, detail: str | None
    ) -> None:
        self.audit_log.append(
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                from_state=from_state,
                to_state=to_state,
                detail=detail,
            )
        )
