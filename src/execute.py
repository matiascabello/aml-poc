"""The effectful action: file a ROS or close an alert.

Simulated for the PoC — it records that it ran and sends nothing to any
external system. What matters is not what the action *does* but that it
categorically cannot run without passing the gate first, regardless of
who calls this function or how.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from gate import ensure_approved
from state_machine import AlertState, TriageAlert

_ACTION_BY_RECOMMENDATION = {
    "escalate": "file_ros",
    "dismiss": "close_alert",
}


@dataclass(frozen=True)
class ExecutionResult:
    alert_id: str
    action: str
    executed_at: datetime
    detail: str


def execute(alert: TriageAlert) -> ExecutionResult:
    """Run the effectful action for an alert.

    THE LOCK: the very first thing this function does is call
    ensure_approved(). There is no branch, flag, or caller identity that
    skips it — this line is the entire guarantee described in CLAUDE.md.

    The transition to `executed` happens inline, right here, after the
    gate check — not via a public method on TriageAlert. That means
    there is no separate primitive anywhere that reaches `executed`
    without first passing ensure_approved().
    """
    ensure_approved(alert)

    action = _ACTION_BY_RECOMMENDATION.get(alert.recommendation)
    if action is None:
        # Should be unreachable: reaching `approved` requires mark_analyzed()
        # to have set a valid recommendation first. Guarded anyway rather
        # than trusting that invariant silently.
        raise RuntimeError(
            f"Alert {alert.alert_id} is approved but has no valid "
            f"recommendation recorded (got {alert.recommendation!r})"
        )

    detail = f"[SIMULATED] {action} for alert {alert.alert_id}"
    result = ExecutionResult(
        alert_id=alert.alert_id,
        action=action,
        executed_at=datetime.now(timezone.utc),
        detail=detail,
    )
    alert._transition(AlertState.EXECUTED, detail=detail)
    return result
