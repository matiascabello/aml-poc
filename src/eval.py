"""Step 4: evals. Grades an LLM backend's output against
data/ground_truth.json on two independent axes:

  1. Recommendation correctness (escalate/dismiss vs ground truth), graded
     by false-negative/false-positive-aware gates, not a flat accuracy
     percentage. With only 6 example alerts, a percentage is not a
     statistically meaningful number -- see format_report()'s footer.
  2. Narrative quality, graded by a deterministic rubric proxy for the
     UIF-style bar in CLAUDE.md: does the narrative cite specific
     amounts/dates/profile facts/counterparties, rather than being
     generic or "defensive."

Ground truth is read here, in this module, and nowhere else -- it is
never imported into alert_data.py or llm_client.py, so the analyzer
never sees it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from alert_data import AlertData, load_alerts
from llm_client import AnalysisResult, LLMClient

DEFAULT_GROUND_TRUTH_PATH = Path(__file__).resolve().parent.parent / "data" / "ground_truth.json"

_MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

# Narratives are Spanish (LATAM regulatory output, see CLAUDE.md) and write
# dates day-first ("22 de julio de 2026"), not month-first like the English
# abbreviations above -- a separate name table and pattern shape, not just a
# translated word list.
_MONTH_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


# --- ground truth -----------------------------------------------------


@dataclass(frozen=True)
class GroundTruthRow:
    alert_id: str
    expected_recommendation: str
    difficulty: str
    rationale: str


def load_ground_truth(path: str | Path = DEFAULT_GROUND_TRUTH_PATH) -> dict[str, GroundTruthRow]:
    with open(path) as f:
        raw = json.load(f)
    return {
        row["alert_id"]: GroundTruthRow(
            alert_id=row["alert_id"],
            expected_recommendation=row["expected_recommendation"],
            difficulty=row["difficulty"],
            rationale=row["rationale"],
        )
        for row in raw
    }


# --- recommendation correctness ----------------------------------------


def classify_recommendation(ground_truth: str, predicted: str) -> str:
    """Positive class = 'escalate'. Returns one of TP/FP/FN/TN.

    FN (missed a truly suspicious/ambiguous case) and FP (escalated an
    innocent one, which a human then clears) are kept as distinct
    outcomes on purpose -- they are not equally bad, and the gates below
    treat them very differently.
    """
    if ground_truth == "escalate" and predicted == "escalate":
        return "TP"
    if ground_truth == "dismiss" and predicted == "escalate":
        return "FP"
    if ground_truth == "escalate" and predicted == "dismiss":
        return "FN"
    return "TN"


@dataclass(frozen=True)
class RecommendationRow:
    alert_id: str
    difficulty: str
    ground_truth: str
    predicted: str
    outcome: str  # TP / FP / FN / TN


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    detail: str


def zero_fn_gate(rows: list[RecommendationRow]) -> GateResult:
    """Hard gate: any missed escalate-labeled alert fails the run,
    regardless of difficulty. Ambiguous-case misses are NOT softened --
    "escalate when in doubt" is the correct AML posture, so dismissing an
    ambiguous alert fails this exactly as hard as dismissing a clear one.
    """
    misses = [r.alert_id for r in rows if r.outcome == "FN"]
    passed = not misses
    detail = (
        "no escalate-labeled alerts were missed"
        if passed
        else f"missed (dismissed) escalate-labeled alert(s): {', '.join(misses)}"
    )
    return GateResult(name="zero_fn_gate", passed=passed, detail=detail)


def discrimination_gate(rows: list[RecommendationRow]) -> GateResult:
    """Hard gate: at least one clear_innocent alert must be correctly
    dismissed. Exists specifically to catch a degenerate "always
    escalate" policy, which would otherwise pass zero_fn_gate for free.
    """
    clear_innocent = [r for r in rows if r.difficulty == "clear_innocent"]
    if not clear_innocent:
        return GateResult(
            name="discrimination_gate",
            passed=True,
            detail="no clear_innocent alerts in this run -- gate not applicable",
        )
    correct = [r.alert_id for r in clear_innocent if r.outcome == "TN"]
    passed = len(correct) >= 1
    detail = (
        f"correctly dismissed {len(correct)}/{len(clear_innocent)} clear_innocent alert(s)"
        if passed
        else (
            f"escalated every clear_innocent alert "
            f"({[r.alert_id for r in clear_innocent]}) -- no evidence of "
            "discrimination between suspicious and innocent activity"
        )
    )
    return GateResult(name="discrimination_gate", passed=passed, detail=detail)


def evaluate_recommendations(
    predictions: dict[str, str],
    ground_truth: dict[str, GroundTruthRow],
) -> list[RecommendationRow]:
    rows = []
    for alert_id, predicted in predictions.items():
        gt = ground_truth[alert_id]
        rows.append(
            RecommendationRow(
                alert_id=alert_id,
                difficulty=gt.difficulty,
                ground_truth=gt.expected_recommendation,
                predicted=predicted,
                outcome=classify_recommendation(gt.expected_recommendation, predicted),
            )
        )
    return rows


# --- narrative rubric (deterministic proxy, Layer 1 only) --------------


def _cites_transaction_amount(alert: AlertData, narrative: str) -> bool:
    for tx in alert.transactions:
        # "9,800" (English), "9.800" (Spanish thousands separator -- the
        # convention this project's narratives actually use), or bare.
        english = f"{tx.amount_usd:,.0f}"
        variants = {english, english.replace(",", "."), str(int(tx.amount_usd))}
        if any(v in narrative for v in variants):
            return True
    return False


def _day_in_a_matched_range(pattern: re.Pattern[str], narrative: str, day: int) -> bool:
    """True if any match of `pattern` covers `day` -- matches carry the day
    (and, for a range, the end day) in groups 1/2 regardless of which
    date pattern produced them.
    """
    for match in pattern.finditer(narrative):
        start_day = int(match.group(1))
        end_day = int(match.group(2)) if match.group(2) else start_day
        if start_day <= day <= end_day:
            return True
    return False


def _cites_transaction_date(alert: AlertData, narrative: str) -> bool:
    """Matches an exact date ("Aug 4, 2026" / "4 de agosto de 2026"), a
    bare month/day, the raw ISO string, or a compressed day range
    ("Jul 22-24, 2026" / "22-24 de julio de 2026") that includes the
    transaction's day -- narratives legitimately compress consecutive
    dates that way, and the checker must not penalize that style as if
    no date were cited at all.

    Narratives are Spanish (see CLAUDE.md), so the Spanish, day-first
    pattern is the one that actually matters in practice -- the English
    pattern is kept for narratives that fall back to the ISO/English
    style (e.g. hand-written test fixtures).
    """
    for tx in alert.transactions:
        if tx.date in narrative:
            return True
        year, month, day = (int(p) for p in tx.date.split("-"))

        month_en = _MONTH_ABBR[month]
        pattern_en = re.compile(
            rf"{month_en}\s+(\d{{1,2}})(?:-(\d{{1,2}}))?(?:,?\s*{year})?",
            re.IGNORECASE,
        )
        if _day_in_a_matched_range(pattern_en, narrative, day):
            return True

        month_es = _MONTH_ES[month]
        pattern_es = re.compile(
            rf"(\d{{1,2}})(?:-(\d{{1,2}}))?\s+de\s+{month_es}(?:\s+de\s+{year})?",
            re.IGNORECASE,
        )
        if _day_in_a_matched_range(pattern_es, narrative, day):
            return True
    return False


def _cites_customer_profile(alert: AlertData, narrative: str) -> bool:
    """Loose, word-level match: narratives paraphrase declared_occupation
    rather than quote it verbatim (e.g. "unemployed" for "Unemployed /
    student"), so this checks for any significant (4+ letter) word from
    the occupation, plus the employer name and the income figure.
    """
    text = narrative.lower()
    customer = alert.customer

    occupation_words = [w for w in re.findall(r"\w+", customer.declared_occupation) if len(w) >= 4]
    if any(w.lower() in text for w in occupation_words):
        return True

    if customer.employer and customer.employer.lower() in text:
        return True

    if customer.declared_monthly_income_usd is not None:
        income = customer.declared_monthly_income_usd
        english = f"{income:,.0f}"
        variants = {english, english.replace(",", "."), str(int(income))}
        if any(v in narrative for v in variants):
            return True

    return False


def _cites_counterparty(alert: AlertData, narrative: str) -> bool | None:
    """None = not applicable: this alert's transactions carry no
    counterparty data to cite in the first place (e.g. cash deposits).
    """
    names = [tx.counterparty_name for tx in alert.transactions if tx.counterparty_name]
    if not names:
        return None
    text = narrative.lower()
    return any(name.lower() in text for name in names)


NARRATIVE_CHECKS = {
    "cites_amount": _cites_transaction_amount,
    "cites_date": _cites_transaction_date,
    "cites_customer_profile": _cites_customer_profile,
    "cites_counterparty": _cites_counterparty,
}


def narrative_checklist(alert: AlertData, narrative: str) -> dict[str, bool | None]:
    return {name: check(alert, narrative) for name, check in NARRATIVE_CHECKS.items()}


def narrative_passes(checklist: dict[str, bool | None]) -> bool:
    """Passes only if every *applicable* check (non-None) is True."""
    return all(value for value in checklist.values() if value is not None)


# --- orchestration --------------------------------------------------------


@dataclass(frozen=True)
class EvalReport:
    recommendation_rows: list[RecommendationRow]
    gates: list[GateResult]
    narrative_checklists: dict[str, dict[str, bool | None]]
    narrative_pass: dict[str, bool]


def run_eval(client: LLMClient, alerts: list[AlertData] | None = None) -> EvalReport:
    alerts = alerts if alerts is not None else load_alerts()
    ground_truth = load_ground_truth()

    predictions: dict[str, AnalysisResult] = {a.alert_id: client.analyze(a) for a in alerts}

    recommendation_rows = evaluate_recommendations(
        {alert_id: result.recommendation for alert_id, result in predictions.items()},
        ground_truth,
    )
    gates = [zero_fn_gate(recommendation_rows), discrimination_gate(recommendation_rows)]

    narrative_checklists = {
        alert.alert_id: narrative_checklist(alert, predictions[alert.alert_id].narrative)
        for alert in alerts
    }
    narrative_pass = {
        alert_id: narrative_passes(checklist) for alert_id, checklist in narrative_checklists.items()
    }

    return EvalReport(
        recommendation_rows=recommendation_rows,
        gates=gates,
        narrative_checklists=narrative_checklists,
        narrative_pass=narrative_pass,
    )


def format_report(report: EvalReport) -> str:
    lines = []

    lines.append("=== Recommendation correctness ===")
    lines.append(f"{'alert_id':<12}{'difficulty':<18}{'ground_truth':<14}{'predicted':<12}outcome")
    for row in report.recommendation_rows:
        lines.append(
            f"{row.alert_id:<12}{row.difficulty:<18}{row.ground_truth:<14}"
            f"{row.predicted:<12}{row.outcome}"
        )
    lines.append("")
    for gate in report.gates:
        status = "PASS" if gate.passed else "FAIL"
        lines.append(f"[{status}] {gate.name}: {gate.detail}")

    lines.append("")
    lines.append("=== Narrative quality (deterministic rubric) ===")
    check_names = list(NARRATIVE_CHECKS)
    header = f"{'alert_id':<12}" + "".join(f"{name:<24}" for name in check_names) + "result"
    lines.append(header)
    for alert_id, checklist in report.narrative_checklists.items():
        cells = []
        for name in check_names:
            value = checklist[name]
            label = "N/A" if value is None else ("PASS" if value else "FAIL")
            cells.append(label.ljust(24))
        result = "PASS" if report.narrative_pass[alert_id] else "FAIL"
        lines.append(f"{alert_id:<12}" + "".join(cells) + result)

    lines.append("")
    lines.append(
        f"NOTE: N={len(report.recommendation_rows)}. This is not a "
        "statistically meaningful accuracy sample -- read the per-alert "
        "rows above, not an aggregate %."
    )
    lines.append(
        "NOTE: the narrative rubric checks fact *presence*, not reasoning "
        "soundness -- it's a floor, not proof the narrative reasons "
        "correctly. See README ADR for the deferred LLM-judge layer."
    )
    return "\n".join(lines)
