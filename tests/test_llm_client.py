"""Tests for the LLM interface, FakeLLMClient, and the LLM_MODE factory.

RealLLMClient itself (network calls to OpenAI) is not exercised here --
see real_llm_client.py and the manual eval run for that. These tests only
cover what's reachable without a network call: the factory's fail-fast
behavior when OPENAI_API_KEY is missing, which is raised in
RealLLMClient.__init__ before any request is made.
"""

from __future__ import annotations

import json
from pathlib import Path

import pydantic
import pytest

from alert_data import load_alerts
from execute import execute
from llm_client import AnalysisResult, FakeLLMClient, get_llm_client
from state_machine import RECOMMENDATIONS, AlertState, TriageAlert

GROUND_TRUTH_PATH = Path(__file__).resolve().parent.parent / "data" / "ground_truth.json"


# --- the factory / LLM_MODE ------------------------------------------


def test_defaults_to_fake_when_llm_mode_is_unset(monkeypatch):
    monkeypatch.delenv("LLM_MODE", raising=False)
    client = get_llm_client()
    assert isinstance(client, FakeLLMClient)


def test_llm_mode_env_var_fake_is_honored(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "fake")
    client = get_llm_client()
    assert isinstance(client, FakeLLMClient)


def test_explicit_mode_argument_overrides_env_var(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "real")
    client = get_llm_client(mode="fake")
    assert isinstance(client, FakeLLMClient)


def test_real_mode_requires_openai_api_key(monkeypatch, tmp_path):
    """RealLLMClient fails fast in __init__, before any network call, if
    OPENAI_API_KEY is missing -- proven here without hitting the network.

    Also points RealLLMClient's .env fallback at a nonexistent path: this
    repo's real .env (used to source the key for LLM_MODE=real runs
    outside tests) would otherwise refill the env var and defeat the
    "missing" case this test exists to prove.
    """
    import real_llm_client

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(real_llm_client, "_ENV_PATH", tmp_path / "nonexistent.env")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        get_llm_client(mode="real")


def test_unknown_mode_raises_value_error():
    with pytest.raises(ValueError):
        get_llm_client(mode="pretend")


# --- FakeLLMClient ------------------------------------------------------


def test_fake_client_returns_a_valid_analysis_for_every_example_alert():
    client = FakeLLMClient()
    for alert in load_alerts():
        result = client.analyze(alert)
        assert isinstance(result, AnalysisResult)
        assert result.recommendation in RECOMMENDATIONS
        assert result.narrative.strip() != ""
        assert len(result.reasoning) > 0


def test_fake_client_is_deterministic():
    client = FakeLLMClient()
    alert = load_alerts()[0]
    assert client.analyze(alert) == client.analyze(alert)


def test_fake_client_raises_clearly_for_unknown_alert_id():
    client = FakeLLMClient()
    unknown = load_alerts()[0]
    # Same shape, id FakeLLMClient has no canned entry for.
    unknown = unknown.__class__(
        alert_id="ALERT-999",
        flagged_at=unknown.flagged_at,
        red_flag=unknown.red_flag,
        customer=unknown.customer,
        transactions=unknown.transactions,
    )
    with pytest.raises(KeyError):
        client.analyze(unknown)


def test_analysis_result_rejects_invalid_recommendation():
    # Pydantic v2's ValidationError is not a subclass of ValueError --
    # verified before writing this, not assumed.
    with pytest.raises(pydantic.ValidationError):
        AnalysisResult(recommendation="approve", narrative="x", reasoning=["a", "b", "c"])


def test_fake_client_recommendations_match_ground_truth_fixture():
    """Sanity cross-check between two static fixture files (canned
    FakeLLMClient responses vs. data/ground_truth.json) -- not the
    analyzer consulting ground truth at runtime. Catches drift if either
    fixture is edited without the other.
    """
    with open(GROUND_TRUTH_PATH) as f:
        ground_truth = {row["alert_id"]: row for row in json.load(f)}

    client = FakeLLMClient()
    for alert in load_alerts():
        result = client.analyze(alert)
        expected = ground_truth[alert.alert_id]["expected_recommendation"]
        assert result.recommendation == expected, (
            f"{alert.alert_id}: FakeLLMClient says {result.recommendation!r}, "
            f"ground truth says {expected!r}"
        )


# --- end-to-end: fake analysis feeding the harness from step 2 --------


def test_fake_analysis_flows_through_the_full_harness():
    alert_data = load_alerts()[0]  # ALERT-001, expected: escalate
    client = FakeLLMClient()
    result = client.analyze(alert_data)

    alert = TriageAlert(alert_id=alert_data.alert_id)
    alert.mark_analyzed(result.recommendation)
    alert.approve()
    execution = execute(alert)

    assert alert.state is AlertState.EXECUTED
    assert execution.action == "file_ros"  # escalate -> file_ros
