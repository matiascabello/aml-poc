"""FastAPI endpoints for the triage UI.

Thin HTTP layer over the existing harness: state_machine.py owns the
states and transition rules, gate.py/execute.py own the approval lock,
llm_client.py owns the analysis call. This module does none of that
work itself -- it loads alerts, looks one up by id, calls the harness,
and translates the harness's exceptions into HTTP status codes.

In-memory only: alert workflow state and analysis results live in
module-level dicts, reset on process restart. Fine for a PoC with no
persistence layer.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from alert_data import AlertData, load_alerts
from execute import execute
from gate import NotApprovedError
from llm_client import AnalysisResult, get_llm_client
from state_machine import InvalidTransitionError, TriageAlert

app = FastAPI(title="AML Alert Triage Assistant")

# alert_id -> AlertData (evidence, immutable, loaded once at startup)
_alerts_by_id: dict[str, AlertData] = {a.alert_id: a for a in load_alerts()}

# alert_id -> TriageAlert (workflow state, one instance per alert, mutated
# in place by mark_analyzed()/approve()/reject()/execute())
_triage_by_id: dict[str, TriageAlert] = {
    alert_id: TriageAlert(alert_id) for alert_id in _alerts_by_id
}

# alert_id -> AnalysisResult, populated by POST /analyze
_analysis_by_id: dict[str, AnalysisResult] = {}


def _get_alert_or_404(alert_id: str) -> tuple[AlertData, TriageAlert]:
    if alert_id not in _alerts_by_id:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id!r} not found")
    return _alerts_by_id[alert_id], _triage_by_id[alert_id]


def _summary(alert: AlertData) -> str:
    return f"{alert.customer.full_name} -- {alert.red_flag.code}"


def _list_item(alert: AlertData, triage: TriageAlert) -> dict:
    return {
        "alert_id": alert.alert_id,
        "summary": _summary(alert),
        "status": triage.state.value,
    }


def _detail(alert: AlertData, triage: TriageAlert) -> dict:
    analysis = _analysis_by_id.get(alert.alert_id)
    return {
        "alert": alert,
        "analysis": analysis,
        "status": triage.state.value,
    }


@app.get("/api/alerts")
def list_alerts() -> list[dict]:
    """Triage inbox: id, short summary, status. No narrative, no ground truth."""
    return [
        _list_item(_alerts_by_id[alert_id], _triage_by_id[alert_id])
        for alert_id in _alerts_by_id
    ]


@app.get("/api/alerts/{alert_id}")
def get_alert(alert_id: str) -> dict:
    """Full detail: raw alert evidence, LLM narrative/recommendation, status."""
    alert, triage = _get_alert_or_404(alert_id)
    return _detail(alert, triage)


@app.post("/api/alerts/{alert_id}/analyze")
def analyze_alert(alert_id: str) -> dict:
    """Run the LLM client (per LLM_MODE), store the result, pending -> analyzed."""
    alert, triage = _get_alert_or_404(alert_id)
    result = get_llm_client().analyze(alert)
    try:
        triage.mark_analyzed(result.recommendation)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _analysis_by_id[alert_id] = result
    return _detail(alert, triage)


@app.post("/api/alerts/{alert_id}/approve")
def approve_alert(alert_id: str) -> dict:
    """analyzed -> approved."""
    alert, triage = _get_alert_or_404(alert_id)
    try:
        triage.approve()
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _detail(alert, triage)


@app.post("/api/alerts/{alert_id}/reject")
def reject_alert(alert_id: str) -> dict:
    """analyzed -> rejected (terminal)."""
    alert, triage = _get_alert_or_404(alert_id)
    try:
        triage.reject()
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _detail(alert, triage)


@app.post("/api/alerts/{alert_id}/execute")
def execute_alert(alert_id: str) -> dict:
    """Run the effectful action. execute() calls ensure_approved() first --
    that check is not reimplemented here, only translated to a 409.
    """
    alert, triage = _get_alert_or_404(alert_id)
    try:
        execute(triage)
    except NotApprovedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _detail(alert, triage)


# Static UI, mounted last so it never shadows the /api/* routes above.
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
