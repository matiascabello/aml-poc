"""Tests for loading the simulated alerts into typed AlertData objects."""

from __future__ import annotations

from alert_data import load_alerts


def test_loads_all_seven_example_alerts_in_order():
    alerts = load_alerts()
    assert [a.alert_id for a in alerts] == [
        "ALERT-001",
        "ALERT-002",
        "ALERT-003",
        "ALERT-004",
        "ALERT-005",
        "ALERT-006",
        "ALERT-007",
    ]


def test_red_flag_and_transactions_parse_correctly():
    alerts = {a.alert_id: a for a in load_alerts()}
    alert = alerts["ALERT-001"]

    assert alert.red_flag.code == "STRUCTURING"
    assert len(alert.transactions) == 3
    assert alert.transactions[0].tx_id == "TX-5001"
    assert alert.transactions[0].amount_usd == 9800


def test_null_income_and_employer_parse_as_none():
    """ALERT-005's customer declared no employer and no income -- both
    must come through as None, not 0 or a missing attribute.
    """
    alerts = {a.alert_id: a for a in load_alerts()}
    customer = alerts["ALERT-005"].customer

    assert customer.employer is None
    assert customer.declared_monthly_income_usd is None


def test_customer_fields_and_pep_flag():
    alerts = {a.alert_id: a for a in load_alerts()}
    customer = alerts["ALERT-004"].customer

    assert customer.is_pep is True
    assert customer.risk_rating == "high"
    assert customer.country == "PY"


def test_counterparty_relationship_is_clean_and_separate_from_name():
    """counterparty_name must never carry a bundled annotation like
    "(sister)" -- that's what counterparty_relationship is for.
    """
    alerts = {a.alert_id: a for a in load_alerts()}

    tx = alerts["ALERT-004"].transactions[0]
    assert tx.counterparty_name == "Marisol Aznárez"
    assert tx.counterparty_relationship == "sister"

    tx = alerts["ALERT-007"].transactions[0]
    assert tx.counterparty_name == "Pan-Atlantic Life Assurance S.A."
    assert tx.counterparty_relationship is None
