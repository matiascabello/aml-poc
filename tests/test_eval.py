"""Fixture-based tests for the eval machinery (src/eval.py). These prove
the grader is correct on synthetic cases where the right answer is
already known -- BEFORE trusting it against the example alerts.
Same discipline as step 2's harness tests: invalid/failure paths get
exercised explicitly, not just the happy path.
"""

from __future__ import annotations

from alert_data import AlertData, Customer, RedFlag, Transaction
from eval import (
    RecommendationRow,
    classify_recommendation,
    discrimination_gate,
    narrative_checklist,
    narrative_passes,
    run_eval,
    zero_fn_gate,
)
from llm_client import FakeLLMClient


def _make_alert(
    alert_id: str = "ALERT-X",
    declared_occupation: str = "Retail worker",
    employer: str | None = "ACME Corp",
    declared_monthly_income_usd: float | None = 2000,
    transactions: list[Transaction] | None = None,
) -> AlertData:
    return AlertData(
        alert_id=alert_id,
        flagged_at="2026-01-01",
        red_flag=RedFlag(code="TEST_FLAG", description="test"),
        customer=Customer(
            customer_id="CUST-X",
            full_name="Test Customer",
            country="AR",
            customer_since="2020-01-01",
            declared_occupation=declared_occupation,
            declared_monthly_income_usd=declared_monthly_income_usd,
            employer=employer,
            is_pep=False,
            risk_rating="low",
            account_type="personal_checking",
        ),
        transactions=transactions
        if transactions is not None
        else [
            Transaction(
                tx_id="TX-X1",
                date="2026-03-15",
                type="wire_in",
                amount_usd=15000,
                channel="wire",
                counterparty_name="Acme Trading Ltd",
                counterparty_relationship=None,
                counterparty_country="PA",
                notes=None,
            )
        ],
    )


def _row(alert_id: str, difficulty: str, ground_truth: str, predicted: str) -> RecommendationRow:
    return RecommendationRow(
        alert_id=alert_id,
        difficulty=difficulty,
        ground_truth=ground_truth,
        predicted=predicted,
        outcome=classify_recommendation(ground_truth, predicted),
    )


# --- classify_recommendation --------------------------------------------


def test_classify_true_positive_correctly_escalated():
    assert classify_recommendation("escalate", "escalate") == "TP"


def test_classify_true_negative_correctly_dismissed():
    assert classify_recommendation("dismiss", "dismiss") == "TN"


def test_classify_false_negative_missed_a_suspicious_case():
    assert classify_recommendation("escalate", "dismiss") == "FN"


def test_classify_false_positive_over_escalated_an_innocent_case():
    assert classify_recommendation("dismiss", "escalate") == "FP"


# --- zero_fn_gate ---------------------------------------------------------


def test_zero_fn_gate_passes_when_no_alert_is_missed():
    rows = [
        _row("A1", "clear_suspicious", "escalate", "escalate"),
        _row("A2", "clear_innocent", "dismiss", "dismiss"),
    ]
    assert zero_fn_gate(rows).passed is True


def test_zero_fn_gate_fails_on_a_clear_suspicious_miss():
    rows = [_row("A1", "clear_suspicious", "escalate", "dismiss")]
    result = zero_fn_gate(rows)
    assert result.passed is False
    assert "A1" in result.detail


def test_zero_fn_gate_fails_on_an_ambiguous_miss_same_as_clear_suspicious():
    """The explicit design decision: ambiguous FNs are NOT softened.
    'Escalate when in doubt' is the correct AML posture, so dismissing an
    ambiguous case fails the gate exactly as hard as dismissing a clear
    one -- this test is what makes that decision load-bearing, not just
    a comment.
    """
    rows = [_row("A1", "ambiguous", "escalate", "dismiss")]
    result = zero_fn_gate(rows)
    assert result.passed is False
    assert "A1" in result.detail


def test_zero_fn_gate_ignores_false_positives():
    """A false positive (wrongly escalating an innocent alert) must not
    trip the FN gate -- that's a separate, lower-severity error type.
    """
    rows = [_row("A1", "clear_innocent", "dismiss", "escalate")]
    assert zero_fn_gate(rows).passed is True


# --- discrimination_gate --------------------------------------------------


def test_discrimination_gate_passes_with_both_clear_innocent_dismissed():
    rows = [
        _row("A1", "clear_innocent", "dismiss", "dismiss"),
        _row("A2", "clear_innocent", "dismiss", "dismiss"),
    ]
    assert discrimination_gate(rows).passed is True


def test_discrimination_gate_passes_with_only_one_of_two_dismissed():
    rows = [
        _row("A1", "clear_innocent", "dismiss", "dismiss"),
        _row("A2", "clear_innocent", "dismiss", "escalate"),
    ]
    assert discrimination_gate(rows).passed is True


def test_discrimination_gate_fails_for_a_degenerate_always_escalate_policy():
    """If every clear_innocent alert also gets escalated, the model isn't
    discriminating at all -- this catches the trivial "always escalate"
    policy that would otherwise pass zero_fn_gate for free.
    """
    rows = [
        _row("A1", "clear_innocent", "dismiss", "escalate"),
        _row("A2", "clear_innocent", "dismiss", "escalate"),
    ]
    assert discrimination_gate(rows).passed is False


def test_discrimination_gate_is_not_applicable_with_no_clear_innocent_rows():
    rows = [_row("A1", "clear_suspicious", "escalate", "escalate")]
    result = discrimination_gate(rows)
    assert result.passed is True
    assert "not applicable" in result.detail


# --- narrative rubric: amount ---------------------------------------------


def test_cites_amount_true_when_exact_comma_formatted_value_present():
    alert = _make_alert(
        transactions=[
            Transaction(
                tx_id="T1", date="2026-01-01", type="wire_in", amount_usd=9800,
                channel="wire", counterparty_name=None, counterparty_relationship=None, counterparty_country=None, notes=None,
            )
        ]
    )
    narrative = "The customer received USD 9,800 via wire."
    assert narrative_checklist(alert, narrative)["cites_amount"] is True


def test_cites_amount_true_when_spanish_period_formatted_value_present():
    """Narratives are Spanish (see CLAUDE.md) and use a period as the
    thousands separator ("USD 9.800"), not an English comma.
    """
    alert = _make_alert(
        transactions=[
            Transaction(
                tx_id="T1", date="2026-01-01", type="wire_in", amount_usd=9800,
                channel="wire", counterparty_name=None, counterparty_relationship=None, counterparty_country=None, notes=None,
            )
        ]
    )
    narrative = "El cliente recibió USD 9.800 por transferencia."
    assert narrative_checklist(alert, narrative)["cites_amount"] is True


def test_cites_amount_false_when_no_figure_present():
    alert = _make_alert()
    narrative = "This transaction appears unusual and warrants further review."
    assert narrative_checklist(alert, narrative)["cites_amount"] is False


# --- narrative rubric: date -------------------------------------------


def test_cites_date_true_for_an_exact_date():
    alert = _make_alert(
        transactions=[
            Transaction(
                tx_id="T1", date="2026-08-04", type="wire_in", amount_usd=1000,
                channel="wire", counterparty_name=None, counterparty_relationship=None, counterparty_country=None, notes=None,
            )
        ]
    )
    narrative = "The wire arrived on Aug 4, 2026."
    assert narrative_checklist(alert, narrative)["cites_date"] is True


def test_cites_date_true_for_a_compressed_day_range():
    """A narrative describing three consecutive-day deposits as
    "Jul 22-24, 2026" is legitimately citing specific dates, just in
    compressed form -- this is exactly the case that motivated
    range-awareness in _cites_transaction_date, caught before the real
    ALERT-001 narrative would have hit it.
    """
    alert = _make_alert(
        transactions=[
            Transaction(
                tx_id="T1", date="2026-07-23", type="cash_deposit", amount_usd=9700,
                channel="branch_cash", counterparty_name=None, counterparty_relationship=None, counterparty_country=None, notes=None,
            )
        ]
    )
    narrative = "Three deposits were made on consecutive days (Jul 22-24, 2026)."
    assert narrative_checklist(alert, narrative)["cites_date"] is True


def test_cites_date_false_when_no_date_mentioned():
    alert = _make_alert()
    narrative = "This transaction is unusual for the customer's profile."
    assert narrative_checklist(alert, narrative)["cites_date"] is False


def test_cites_date_true_for_a_spanish_exact_date():
    """Narratives are Spanish (see CLAUDE.md) and write dates day-first
    ("4 de agosto de 2026"), not month-first like the English fixtures
    above -- this is the format real narratives actually use.
    """
    alert = _make_alert(
        transactions=[
            Transaction(
                tx_id="T1", date="2026-08-04", type="wire_in", amount_usd=1000,
                channel="wire", counterparty_name=None, counterparty_relationship=None, counterparty_country=None, notes=None,
            )
        ]
    )
    narrative = "La transferencia llegó el 4 de agosto de 2026."
    assert narrative_checklist(alert, narrative)["cites_date"] is True


def test_cites_date_true_for_a_spanish_compressed_day_range():
    alert = _make_alert(
        transactions=[
            Transaction(
                tx_id="T1", date="2026-07-23", type="cash_deposit", amount_usd=9700,
                channel="branch_cash", counterparty_name=None, counterparty_relationship=None, counterparty_country=None, notes=None,
            )
        ]
    )
    narrative = "Tres depósitos en días consecutivos (22-24 de julio de 2026)."
    assert narrative_checklist(alert, narrative)["cites_date"] is True


# --- narrative rubric: customer profile ---------------------------------


def test_cites_customer_profile_true_via_paraphrased_occupation():
    alert = _make_alert(
        declared_occupation="Unemployed / student", employer=None,
        declared_monthly_income_usd=None,
    )
    narrative = "The customer is unemployed and has no other declared income."
    assert narrative_checklist(alert, narrative)["cites_customer_profile"] is True


def test_cites_customer_profile_true_via_income_figure():
    alert = _make_alert(declared_occupation="Architect", declared_monthly_income_usd=3800)
    narrative = "Declared monthly income of USD 3,800."
    assert narrative_checklist(alert, narrative)["cites_customer_profile"] is True


def test_cites_customer_profile_false_when_profile_never_mentioned():
    alert = _make_alert()
    narrative = "This transaction is unusual and warrants further review."
    assert narrative_checklist(alert, narrative)["cites_customer_profile"] is False


# --- narrative rubric: counterparty ---------------------------------------


def test_cites_counterparty_true_when_name_present():
    alert = _make_alert()  # default transaction's counterparty is "Acme Trading Ltd"
    narrative = "Funds were received from Acme Trading Ltd."
    assert narrative_checklist(alert, narrative)["cites_counterparty"] is True


def test_cites_counterparty_false_when_named_but_not_mentioned():
    alert = _make_alert()
    narrative = "An unusually large wire was received."
    assert narrative_checklist(alert, narrative)["cites_counterparty"] is False


def test_cites_counterparty_is_not_applicable_with_no_counterparty_data():
    alert = _make_alert(
        transactions=[
            Transaction(
                tx_id="T1", date="2026-01-01", type="cash_deposit", amount_usd=9800,
                channel="branch_cash", counterparty_name=None, counterparty_relationship=None, counterparty_country=None, notes=None,
            )
        ]
    )
    narrative = "A cash deposit of USD 9,800 was made."
    assert narrative_checklist(alert, narrative)["cites_counterparty"] is None


# --- narrative_passes -----------------------------------------------------


def test_narrative_passes_requires_all_applicable_checks_true():
    checklist = {"a": True, "b": True, "c": None}
    assert narrative_passes(checklist) is True


def test_narrative_passes_false_if_any_applicable_check_fails():
    checklist = {"a": True, "b": False, "c": None}
    assert narrative_passes(checklist) is False


def test_narrative_passes_false_for_a_generic_defensive_narrative():
    """The end-to-end proof this rubric exists for: a generic,
    evidence-free narrative -- exactly what CLAUDE.md's quality bar
    calls out as a bad narrative -- must fail, not pass.
    """
    alert = _make_alert()
    generic_narrative = "This activity appears unusual and is recommended for further review."
    checklist = narrative_checklist(alert, generic_narrative)
    assert narrative_passes(checklist) is False


# --- integration: the grader (now proven above) against FakeLLMClient ---


def test_fake_llm_client_passes_both_gates_and_every_narrative_check():
    """Locks in the verified current state: FakeLLMClient's hand-written
    canned responses clear both recommendation gates and every applicable
    narrative rubric check. This is expected precisely because those
    narratives were written carefully, not because the eval is lenient --
    the fixture tests above already prove the grader fails cases that
    should fail (a generic narrative, a missed escalate-labeled alert).
    A regression here means a canned response changed, not that grading
    got stricter.
    """
    report = run_eval(FakeLLMClient())

    for gate in report.gates:
        assert gate.passed is True, f"{gate.name} failed: {gate.detail}"

    for alert_id, passed in report.narrative_pass.items():
        assert passed is True, f"{alert_id} failed its narrative rubric: {report.narrative_checklists[alert_id]}"
