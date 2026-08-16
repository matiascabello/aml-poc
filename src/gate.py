"""The approval gate.

This is the single choke point every execution path must pass through.
It has one job: refuse to proceed unless the alert's state is `approved`.
It knows nothing about the LLM, the UI, or how it was invoked — it only
looks at `alert.state`, which is why it can't be talked around.
"""

from __future__ import annotations

from state_machine import AlertState, TriageAlert


class NotApprovedError(Exception):
    """Raised when execution is attempted on an alert that is not approved."""


def ensure_approved(alert: TriageAlert) -> None:
    if alert.state is not AlertState.APPROVED:
        raise NotApprovedError(
            f"Alert {alert.alert_id} is not approved (state={alert.state.value!r}); "
            "refusing to execute."
        )
