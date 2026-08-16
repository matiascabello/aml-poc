"""Tests for the gate and execute(). This file contains the single most
important test in the project: execute() refuses to run on anything but
an approved alert, and it refuses even when called directly — with no
UI, no approval workflow, nothing standing between the caller and the
function itself. That direct-call guarantee is the whole point of
CLAUDE.md's "non-negotiable architecture principle": the lock is in
code, not in the prompt or the UI, so nothing upstream of execute() can
be trusted to enforce it, and none of it needs to be.
"""

from __future__ import annotations

import pytest

from execute import ExecutionResult, execute
from gate import NotApprovedError, ensure_approved
from state_machine import AlertState, InvalidTransitionError, TriageAlert


def make_alert(alert_id: str = "ALERT-TEST") -> TriageAlert:
    return TriageAlert(alert_id=alert_id)


def make_approved_alert(recommendation: str = "escalate") -> TriageAlert:
    alert = make_alert()
    alert.mark_analyzed(recommendation)
    alert.approve()
    return alert


# --- the key test ---------------------------------------------------------


def _pending_alert() -> TriageAlert:
    return make_alert()


def _analyzed_alert() -> TriageAlert:
    alert = make_alert()
    alert.mark_analyzed("escalate")
    return alert


def _rejected_alert() -> TriageAlert:
    alert = make_alert()
    alert.mark_analyzed("dismiss")
    alert.reject()
    return alert


def _already_executed_alert() -> TriageAlert:
    alert = make_alert()
    alert.mark_analyzed("escalate")
    alert.approve()
    execute(alert)  # the only legitimate way to reach `executed`
    return alert


@pytest.mark.parametrize(
    "build_alert",
    [
        pytest.param(_pending_alert, id="pending"),
        pytest.param(_analyzed_alert, id="analyzed"),
        pytest.param(_rejected_alert, id="rejected"),
        pytest.param(_already_executed_alert, id="already_executed"),
    ],
)
def test_execute_on_non_approved_alert_raises_even_when_called_directly(build_alert):
    """Core guarantee: for every state other than `approved`, calling
    execute() directly — bypassing any approve()/UI step entirely —
    raises NotApprovedError instead of performing the action.
    """
    alert = build_alert()
    assert alert.state is not AlertState.APPROVED
    state_before = alert.state
    audit_log_length_before = len(alert.audit_log)

    with pytest.raises(NotApprovedError):
        execute(alert)

    # And critically: nothing happened. The blocked call didn't change
    # state or add anything to the audit log — not even a failed attempt.
    assert alert.state is state_before
    assert len(alert.audit_log) == audit_log_length_before


def test_gate_ensure_approved_raises_directly_too():
    """The gate function itself, called with zero ceremony, refuses a
    non-approved alert. execute() has no special knowledge here — this
    is the exact check it relies on.
    """
    alert = make_alert()
    with pytest.raises(NotApprovedError):
        ensure_approved(alert)


def test_gate_ensure_approved_passes_silently_when_approved():
    alert = make_approved_alert()
    ensure_approved(alert)  # should not raise


# --- happy path -------------------------------------------------------


def test_execute_runs_on_approved_alert_and_transitions_to_executed():
    alert = make_approved_alert("escalate")
    result = execute(alert)

    assert isinstance(result, ExecutionResult)
    assert alert.state is AlertState.EXECUTED
    assert result.alert_id == alert.alert_id


def test_execute_files_ros_for_escalate_recommendation():
    alert = make_approved_alert("escalate")
    result = execute(alert)
    assert result.action == "file_ros"


def test_execute_closes_alert_for_dismiss_recommendation():
    alert = make_approved_alert("dismiss")
    result = execute(alert)
    assert result.action == "close_alert"


def test_execute_records_the_action_in_the_audit_log():
    alert = make_approved_alert("escalate")
    execute(alert)
    last_entry = alert.audit_log[-1]
    assert last_entry.to_state is AlertState.EXECUTED
    assert "file_ros" in last_entry.detail


def test_double_execute_is_refused_by_the_gate_not_just_the_state_machine():
    """Once executed, calling execute() again must be stopped by the gate
    (NotApprovedError) — proving the gate check runs on every call, not
    only the first one.
    """
    alert = make_approved_alert("escalate")
    execute(alert)
    assert alert.state is AlertState.EXECUTED

    with pytest.raises(NotApprovedError):
        execute(alert)


def test_execute_stub_sends_nothing_only_records_that_it_ran():
    """The action is simulated: verify it produces a local record and
    does not, for example, require or touch any external client/network
    dependency (none is imported by src/execute.py).
    """
    alert = make_approved_alert("dismiss")
    result = execute(alert)
    assert result.detail.startswith("[SIMULATED]")
