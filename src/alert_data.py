"""Typed representation of the simulated alerts in data/alerts.json.

This is the shape the LLM analyzer (and later the UI) reads. It mirrors
the JSON exactly — no eval ground truth, no derived fields, nothing the
alert-generation pipeline wouldn't have produced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ALERTS_PATH = Path(__file__).resolve().parent.parent / "data" / "alerts.json"


@dataclass(frozen=True)
class RedFlag:
    code: str
    description: str


@dataclass(frozen=True)
class Customer:
    customer_id: str
    full_name: str
    country: str
    customer_since: str
    declared_occupation: str
    declared_monthly_income_usd: float | None
    employer: str | None
    is_pep: bool
    risk_rating: str
    account_type: str


@dataclass(frozen=True)
class Transaction:
    tx_id: str
    date: str
    type: str
    amount_usd: float
    channel: str
    counterparty_name: str | None
    counterparty_relationship: str | None  # e.g. "sister"; None if unrelated/unknown
    counterparty_country: str | None
    notes: str | None


@dataclass(frozen=True)
class AlertData:
    alert_id: str
    flagged_at: str
    red_flag: RedFlag
    customer: Customer
    transactions: list[Transaction]

    @classmethod
    def from_dict(cls, data: dict) -> "AlertData":
        return cls(
            alert_id=data["alert_id"],
            flagged_at=data["flagged_at"],
            red_flag=RedFlag(**data["red_flag"]),
            customer=Customer(**data["customer"]),
            transactions=[Transaction(**tx) for tx in data["transactions"]],
        )


def load_alerts(path: str | Path = DEFAULT_ALERTS_PATH) -> list[AlertData]:
    with open(path) as f:
        raw = json.load(f)
    return [AlertData.from_dict(item) for item in raw]
