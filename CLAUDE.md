# CLAUDE.md — AML Alert Triage Assistant

This file is the stable context; individual tasks are given turn by turn.

**Guiding principle: SIMPLE.** This is a proof of concept. A clean, minimal,
working PoC beats a polished, over-engineered one. Do not add abstraction,
frameworks, or features beyond what a step requires.

---

## The case

An internal agent for **compliance analysts** at a LATAM financial institution.
A transaction-monitoring system has already flagged suspicious activity — we do
NOT build the detection engine; alerts are simulated input. For each alert, the
agent:

1. Reads the alert evidence (customer KYC profile, the transactions, the
   GAFI/FATF red flag that triggered it).
2. Produces a **recommendation** (escalate to a Suspicious Activity Report /
   dismiss) plus a written **narrative** explaining WHY, cross-referencing the
   transactions against the customer profile.
3. A human compliance analyst reviews, may edit the narrative, and approves or
   rejects.
4. Code executes the effectful action — file the report (simulated) or close the
   alert with justification — ONLY if approved.

**Why this case genuinely needs an LLM.** LATAM regulators (the UIF / GAFILAT
framework) require a suspicious-activity report to include a detailed, reasoned narrative, not a generic flag. Writing that reasoning over unstructured, heterogeneous evidence (transactions vs. declared profile vs. jurisdiction) is exactly what an LLM does well and a template cannot. The LLM is not decorative here — the narrative is a real regulatory artifact.

Regional terms: the report is a **ROS** (Reporte de Operación Sospechosa),
filed to the country's **UIF** (Unidad de Información/Inteligencia Financiera).

---

## Non-negotiable architecture principle

The effectful action (file report / close alert) is guaranteed by **code, not by
the prompt**. The LLM analyzes and drafts — it does NOT have access to the execute function. Filing/closing is a code function that checks the state is `approved` before it runs. If there is no approval, it does not run — whether you ask the LLM or call the function directly. That code-level lock is the heart of the exercise.

The demo that proves it: attempt to file a ROS on an alert nobody approved →
the code refuses, because `execute()` checks state. Works even when called
directly, bypassing the UI.

---

## The pieces

- **Simulated alerts** — a JSON file. Each alert: customer/KYC profile, the
  triggering transactions, the red-flag type.
- **Analyzer** — calls the LLM, returns recommendation + narrative + reasoning.
- **State machine** — `pending → analyzed → approved → executed`, with `rejected`
  as the terminal alternative to `approved`.
- **Gate** — verifies state + approval before any execution.
- **Action** (file report / close alert) — a code function that only runs on
  `approved` alerts.
- **Lightweight web UI** — list of alerts, view analysis, approve/reject.

## Model vs. code split

- **Code decides/guarantees:** the state machine, the approval gate, the execute
  function (file/close), the audit log. The LLM cannot bypass any of this.
- **The LLM decides:** reads one alert, returns a structured recommendation +
  narrative + reasoning. Its output is a proposal a human reviews — it triggers
  no action by itself.

## Canonical vocabulary (use these exact identifiers in code)

- States: `pending → analyzed → approved → executed`; `rejected` is terminal.
- Recommendations: `escalate` (to ROS) / `dismiss`.

---

## Stack

- Python backend (FastAPI), plain Python — no agent framework (see ADR below).
- uv for environment and dependency management (not pip/poetry). Use uv for installing dependencies and running the project.
- Lightweight web UI as a thin client over the backend.
- Simulated data, no real integrations.

**On "no real integrations":** the brief's phrase refers to the institution's
systems (core banking, transaction monitoring, the UIF portal, messaging) — all
simulated. The LLM is the agent's engine; calling it is what makes the prototype
functional.

---

## LLM layer (reproducibility)

Put the LLM call behind a single interface (e.g. `analyze(alert) ->
Recommendation`) with two interchangeable implementations, selected by an
explicit config flag — NOT by the presence of a credential:

    LLM_MODE=fake   # default — runs with no API key, fully reproducible
    LLM_MODE=real   # opt-in — requires an API key (via env var)

A factory (e.g. `get_llm_client()`) returns `FakeLLMClient` (canned responses for
the example alerts) or `RealLLMClient` based on the flag. The rest of the system —
harness, gate, UI, tests — is identical in both modes and never checks the mode
itself; it just calls the interface. The project runs end-to-end with `fake` by
default, so it is reproducible locally with zero setup, and the eval/test suite
gets deterministic LLM output to test the harness independently of model quality.
The API key is just data the real mode needs, never the switch.

---

## Build order (harness first, tests first; UI last)

1. **Data model + simulated alerts** — the alert shape (KYC profile,
   transactions, red flag) and 5–6 examples covering suspicious / innocent /
   ambiguous. The eval ground truth (expected recommendation) lives separately
   from what the LLM sees — never inside the alert the analyzer receives.
2. **Core harness** — state machine + gate + execute function, pure Python, WITH
   TESTS. Includes the key test: "executing on a non-approved alert raises an
   exception," verified even when called directly (bypassing the UI). No LLM, no
   UI yet.
3. **LLM layer** — the interface + `FakeLLMClient` + `RealLLMClient` + the
   `LLM_MODE` flag. Get `fake` running end-to-end first; `real` second.
4. **Evals** — metric and threshold defined BEFORE measuring. Include hard cases
   where the agent fails. Quality signal drawn from a real regulator critique
   (Argentina's UIF): a good narrative explains the specific reason for suspicion
   and breaks down the evidence (amounts, dates, counterparties); a bad one is
   generic or "defensive." Eval the narratives on that.
5. **Lightweight web UI** — list, view analysis, approve/reject.
6. **README** — setup + agent architecture (what the model decides vs. what the
   code guarantees) + ADR-style decision log.

Steps 2 and 3 stay separate: step 2 proves control lives in code WITHOUT the LLM
in the picture; step 3 adds the model on top without touching the lock.

---

## Working rules

- Verify current library and model versions before writing code — don't assume
  from training data.
- Readable, minimal, reproducible. This is a PoC that engineering will later
  productize; the PM's validations pass to engineering to harden.
- Log decisions ADR-style in the README as you make them: what you decided, what
  alternatives you considered, what tradeoff you accepted. Write each ADR in the
  step where the decision happens, not all at the end.

---

## Design decisions to document as ADRs

**Plain Python, not LangGraph.** The flow is essentially linear (single LLM call
→ human gate → code execution), a single agent, no cycle. LangGraph earns its
place with multi-agent graphs and loops; here it adds abstraction without benefit
and buries the control point the exercise is about. In the README ADR: (a) sketch
how this would look in LangGraph (nodes: analyze → human_gate → execute, state
flowing between them), and (b) explain why plain Python was chosen — more
explicit, more auditable control. This shows awareness of agent platforms and the
judgment to know when not to use one.

**Interchangeable LLM layer.** (See "LLM layer" above.) Abstracting the provider
behind an interface with a fake/real switch gives reproducibility, deterministic
tests, and provider independence — document the tradeoff (writing canned
responses) as accepted.