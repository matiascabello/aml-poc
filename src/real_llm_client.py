"""RealLLMClient: OpenAI-backed implementation of LLMClient.

All OpenAI-specific code -- the SDK import, the model choice, the
prompt, the structured-output call -- is contained in this module.
Nothing outside it knows or needs to know the provider is OpenAI;
swapping this file for a different provider leaves the rest of the
system (harness, gate, eval, UI) untouched. get_llm_client() imports it
lazily, only when LLM_MODE=real is actually resolved.

Verified 2026-08-15 (see README ADR):
  - openai Python SDK 3.1.0 (PyPI, released 2026-08-14).
  - model "gpt-5.6-luna" -- confirmed against developers.openai.com/api/docs/models,
    OpenAI's cost-optimized GPT-5.6 tier ($0.20/$1.20 per MTok, 1.05M context).
  - Structured output via the Responses API's client.responses.parse(...,
    text_format=<PydanticModel>) -- not manual JSON-mode + regex parsing.
    AnalysisResult (llm_client.py) is passed directly as text_format, so a
    non-conforming response fails the call rather than being coerced.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from alert_data import AlertData, Transaction
from llm_client import AnalysisResult, LLMClient

DEFAULT_MODEL = "gpt-5.6-luna"

# Explicit path, not CWD-relative load_dotenv(), matching alert_data.py's
# DEFAULT_ALERTS_PATH: works regardless of where `uv run` is invoked
# from. A module-level constant (not inlined in __init__) so a test can
# monkeypatch it to a nonexistent path and prove the "no key anywhere"
# case without a real .env file getting in the way.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class LLMOutputError(Exception):
    """Raised when OpenAI does not return a schema-conforming analysis --
    a refusal, a parse failure, or empty content. Fails loudly rather
    than silently coercing or guessing at a recommendation.
    """


_SYSTEM_PROMPT = """\
You are an AML (Anti-Money Laundering) compliance analysis assistant for a \
financial institution operating under LATAM regulatory frameworks (UIF / \
GAFILAT, aligned with GAFI/FATF standards).

You are given one alert that a transaction-monitoring system has already \
flagged: the customer's declared KYC profile, the specific transactions \
that triggered the alert, and the red-flag category that fired. Decide \
whether this alert should be ESCALATED (filed as a ROS -- Reporte de \
Operación Sospechosa -- to the UIF) or DISMISSED (closed as a false \
positive), and write the narrative that would accompany that decision. A \
human compliance analyst reviews your recommendation before anything is \
filed or closed -- you are drafting a proposal for that human, not taking \
the action yourself.

Write the `narrative` and `reasoning` fields in Spanish -- the users of \
this system are compliance analysts at LATAM financial institutions, and \
the narrative is a draft of a regulatory document (the ROS) that must \
already read like one. Write amounts with a period as the thousands \
separator (e.g. "USD 9.800", not "USD 9,800") and dates day-first with \
the Spanish month name (e.g. "4 de agosto de 2026"), matching how a \
Spanish-language ROS narrative is actually written. The `recommendation` \
field is the one exception: it is a fixed code, not prose -- always \
return exactly "escalate" or "dismiss", in English, unchanged.

How to decide:
- "escalate": the activity is inconsistent with the customer's declared \
profile, a plausible innocent explanation lacks supporting documentation \
on file, or the pattern matches a known typology (structuring, rapid \
pass-through/mule activity, unexplained wealth relative to declared \
income, etc.). When genuinely in doubt, escalate: a human reviews every \
escalation before any report is filed, so escalation is the conservative, \
safe default. A missed truly suspicious case is a far more serious \
failure than an unnecessary escalation a human then clears in minutes.
- "dismiss": the evidence is well-explained by the customer's declared \
profile and account history, with no material gap or unexplained red \
flag beyond the one that triggered the alert.

Narrative requirements (this is graded against the actual standard used \
by UIF examiners -- generic narratives are treated as regulatory \
failures, not just weak writing):
- State the SPECIFIC reason for suspicion, or for clearing it. Never \
write something like "this transaction appears unusual and warrants \
review" -- that sentence could be pasted onto any alert and is exactly \
what you must not produce.
- Break down the evidence explicitly: cite exact transaction amounts in \
USD, exact dates, and counterparty names/jurisdictions where present in \
the data.
- Cross-reference the transactions against the customer's declared \
profile -- occupation, declared monthly income, employer, PEP status, \
KYC risk rating -- and say concretely how the activity does or does not \
fit that profile (e.g. express an amount as a multiple of declared \
monthly income when that comparison is meaningful).
- The narrative must only make sense for this specific alert. If it \
would read the same way pasted onto a different alert, rewrite it.

Also provide 3-6 reasoning bullet points: discrete, concrete, \
evidence-grounded observations that support the recommendation (not a \
summary of the narrative) -- these are what a human reviewer scans first \
to sanity-check your conclusion before reading the full narrative.

Respond only in the requested structured format. No disclaimers, no \
hedging about not being a lawyer or compliance officer, no meta-commentary \
about your process.
"""


def _format_transaction(tx: Transaction) -> str:
    counterparty = (
        f"{tx.counterparty_name} ({tx.counterparty_country})" if tx.counterparty_name else "none"
    )
    # Relationship is a distinct, structured field -- not folded back into
    # the counterparty string -- so the model gets it as a fact to reason
    # over (e.g. "sister" is part of why a family-loan story is both
    # plausible and needs scrutiny), not as decoration on a name.
    relationship = tx.counterparty_relationship or "none"
    return (
        f"  - {tx.date} | {tx.type} | USD {tx.amount_usd:,.0f} | channel: {tx.channel} "
        f"| counterparty: {counterparty} | relationship to customer: {relationship} "
        f"| notes: {tx.notes or 'none'}"
    )


def _format_alert_for_prompt(alert: AlertData) -> str:
    customer = alert.customer
    income = (
        f"{customer.declared_monthly_income_usd:,.0f}"
        if customer.declared_monthly_income_usd is not None
        else "not declared"
    )
    lines = [
        f"ALERT ID: {alert.alert_id}",
        f"FLAGGED AT: {alert.flagged_at}",
        f"RED FLAG: {alert.red_flag.code} -- {alert.red_flag.description}",
        "",
        "CUSTOMER PROFILE (as declared / on file at KYC):",
        f"  Name: {customer.full_name} ({customer.customer_id})",
        f"  Country: {customer.country}",
        f"  Customer since: {customer.customer_since}",
        f"  Declared occupation: {customer.declared_occupation}",
        f"  Declared monthly income (USD): {income}",
        f"  Employer: {customer.employer or 'none on file'}",
        f"  Politically exposed person (PEP): {'yes' if customer.is_pep else 'no'}",
        f"  KYC risk rating: {customer.risk_rating}",
        f"  Account type: {customer.account_type}",
        "",
        "TRANSACTIONS THAT TRIGGERED / SURROUND THIS ALERT:",
    ]
    lines.extend(_format_transaction(tx) for tx in alert.transactions)
    return "\n".join(lines)


def _extract_refusal(response) -> str | None:
    for output in response.output:
        if output.type != "message":
            continue
        for item in output.content:
            if item.type == "refusal":
                return item.refusal
    return None


class RealLLMClient(LLMClient):
    """LLM_MODE=real backend. Calls OpenAI's Responses API with
    AnalysisResult as a strict structured-output schema -- never
    free-text + regex.
    """

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None) -> None:
        # Called on every construction, not just at first import: cheap
        # (reads one small file), and keeps the fallback scoped to
        # exactly this call rather than a process-lifetime side effect
        # from whenever this module first happened to be imported.
        # Never overrides a key already set in the real environment --
        # .env is a fallback source, not an authority.
        load_dotenv(_ENV_PATH)
        resolved_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "LLM_MODE=real requires OPENAI_API_KEY to be set (directly "
                "or via the api_key argument). Use LLM_MODE=fake (the "
                "default) to run without an API key."
            )
        self._model = model
        self._client = OpenAI(api_key=resolved_key)

    def analyze(self, alert: AlertData) -> AnalysisResult:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _format_alert_for_prompt(alert)},
            ],
            text_format=AnalysisResult,
        )

        parsed = response.output_parsed
        if parsed is None:
            refusal = _extract_refusal(response)
            raise LLMOutputError(
                f"OpenAI did not return a schema-conforming analysis for "
                f"alert {alert.alert_id!r}"
                + (f": refused -- {refusal}" if refusal else " (no refusal message; unknown cause)")
            )
        if not parsed.narrative.strip():
            raise LLMOutputError(f"OpenAI returned an empty narrative for alert {alert.alert_id!r}")

        return parsed
