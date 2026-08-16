"""Tests for the alert state machine: valid transitions, and — just as
important — that invalid transitions are rejected rather than silently
allowed or ignored.
"""

from __future__ import annotations

import pytest

from state_machine import AlertState, InvalidTransitionError, TriageAlert


def make_alert(alert_id: str = "ALERT-TEST") -> TriageAlert:
    return TriageAlert(alert_id=alert_id)


# --- happy path -------------------------------------------------------


def test_new_alert_starts_pending():
    alert = make_alert()
    assert alert.state is AlertState.PENDING
    assert alert.recommendation is None


def test_full_happy_path_pending_to_approved():
    alert = make_alert()
    alert.mark_analyzed("escalate")
    assert alert.state is AlertState.ANALYZED
    assert alert.recommendation == "escalate"

    alert.approve()
    assert alert.state is AlertState.APPROVED


def test_analyzed_can_be_rejected_instead_of_approved():
    alert = make_alert()
    alert.mark_analyzed("dismiss")
    alert.reject(reason="False positive, matches declared profile")
    assert alert.state is AlertState.REJECTED


def test_mark_analyzed_rejects_unknown_recommendation():
    alert = make_alert()
    with pytest.raises(ValueError):
        alert.mark_analyzed("maybe")
    # Rejected before any state mutation happened.
    assert alert.state is AlertState.PENDING


# --- invalid transitions: the machine must refuse these ---------------


def test_cannot_skip_straight_from_pending_to_approved():
    alert = make_alert()
    with pytest.raises(InvalidTransitionError):
        alert.approve()
    assert alert.state is AlertState.PENDING


def test_cannot_skip_straight_from_pending_to_executed():
    alert = make_alert()
    with pytest.raises(InvalidTransitionError):
        # There is no public "mark executed" primitive to call here — the
        # only sanctioned path to `executed` is execute() in execute.py,
        # after ensure_approved() passes. Reaching into `_transition`
        # directly is legitimate in this file: it's testing the state
        # machine's own internals, not bypassing execute.py's contract.
        alert._transition(AlertState.EXECUTED, detail="attempted skip")
    assert alert.state is AlertState.PENDING


def test_cannot_reject_a_pending_alert_before_analysis():
    alert = make_alert()
    with pytest.raises(InvalidTransitionError):
        alert.reject("skipping analysis")
    assert alert.state is AlertState.PENDING


def test_cannot_analyze_an_already_analyzed_alert():
    alert = make_alert()
    alert.mark_analyzed("escalate")
    with pytest.raises(InvalidTransitionError):
        alert.mark_analyzed("dismiss")
    # State and original recommendation are untouched by the failed attempt.
    assert alert.state is AlertState.ANALYZED
    assert alert.recommendation == "escalate"


def test_cannot_approve_an_already_approved_alert():
    alert = make_alert()
    alert.mark_analyzed("escalate")
    alert.approve()
    with pytest.raises(InvalidTransitionError):
        alert.approve()
    assert alert.state is AlertState.APPROVED


def test_cannot_approve_an_already_executed_alert():
    alert = make_alert()
    alert.mark_analyzed("escalate")
    alert.approve()
    alert._transition(AlertState.EXECUTED, detail="filed")
    with pytest.raises(InvalidTransitionError):
        alert.approve()
    assert alert.state is AlertState.EXECUTED


def test_rejected_is_terminal():
    alert = make_alert()
    alert.mark_analyzed("dismiss")
    alert.reject()

    with pytest.raises(InvalidTransitionError):
        alert.approve()
    with pytest.raises(InvalidTransitionError):
        alert.mark_analyzed("escalate")
    with pytest.raises(InvalidTransitionError):
        alert._transition(AlertState.EXECUTED, detail="should not run")
    assert alert.state is AlertState.REJECTED


def test_executed_is_terminal():
    alert = make_alert()
    alert.mark_analyzed("escalate")
    alert.approve()
    alert._transition(AlertState.EXECUTED, detail="filed")
    with pytest.raises(InvalidTransitionError):
        alert._transition(AlertState.EXECUTED, detail="filed again")
    with pytest.raises(InvalidTransitionError):
        alert.approve()
    assert alert.state is AlertState.EXECUTED


# --- audit log ----------------------------------------------------------


def test_every_transition_is_recorded_with_a_timestamp():
    alert = make_alert()
    alert.mark_analyzed("escalate")
    alert.approve()
    alert._transition(AlertState.EXECUTED, detail="filed")

    # creation + 3 transitions
    assert len(alert.audit_log) == 4

    states_seen = [entry.to_state for entry in alert.audit_log]
    assert states_seen == [
        AlertState.PENDING,
        AlertState.ANALYZED,
        AlertState.APPROVED,
        AlertState.EXECUTED,
    ]
    for entry in alert.audit_log:
        assert entry.timestamp is not None


def test_failed_transition_attempts_are_not_added_to_the_audit_log():
    alert = make_alert()
    entries_before = len(alert.audit_log)
    with pytest.raises(InvalidTransitionError):
        alert.approve()
    assert len(alert.audit_log) == entries_before
