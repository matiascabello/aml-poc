"""The LLM layer: one interface, swappable backends, selected by LLM_MODE.

LLM_MODE=fake   # default — canned responses, no API key, fully reproducible
LLM_MODE=real   # opt-in — calls OpenAI's API (see real_llm_client.py);
                # requires OPENAI_API_KEY

Nothing outside this module — harness, gate, UI, tests — ever checks the
mode itself; everything calls LLMClient.analyze() and gets an
AnalysisResult back, regardless of which backend produced it.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from alert_data import AlertData

# Loaded once at import time, not inside get_llm_client(): the LLM_MODE
# lookup below reads os.environ directly, and "uv run ..." does not load
# .env on its own, so without this, editing LLM_MODE in .env silently has
# no effect and the factory keeps defaulting to fake. Explicit path (not
# CWD-relative), matching real_llm_client.py's own _ENV_PATH, so this
# works regardless of where the process is launched from. Never overrides
# a key already set in the real environment -- .env is a fallback source,
# not an authority (load_dotenv()'s default: don't clobber existing vars).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class AnalysisResult(BaseModel):
    """The LLM's structured output for one alert — what CLAUDE.md's sketch
    `analyze(alert) -> Recommendation` returns: a recommendation, the
    regulator-facing narrative, and the evidence trail behind it.

    One Pydantic definition, shared by FakeLLMClient, RealLLMClient, and
    eval.py — not a dataclass FakeLLMClient uses and a separate schema
    RealLLMClient invents. RealLLMClient passes this class directly as
    OpenAI's structured-output `text_format`, so a real response either
    comes back as a valid AnalysisResult or the call fails loudly.
    """

    model_config = ConfigDict(frozen=True)

    recommendation: Literal["escalate", "dismiss"]
    narrative: str  # ROS-ready narrative, cross-references transactions vs. profile
    reasoning: list[str] = Field(min_length=3, max_length=6)  # evidence points behind the narrative


class LLMClient(ABC):
    """Interface every LLM backend implements. Swapping FakeLLMClient for
    RealLLMClient is invisible to everything downstream of this class.
    """

    @abstractmethod
    def analyze(self, alert: AlertData) -> AnalysisResult:
        """Read one alert's evidence and return a structured recommendation."""


class FakeLLMClient(LLMClient):
    """Deterministic, canned responses for the example alerts in
    data/alerts.json. No network call, no API key — this is what
    LLM_MODE=fake runs, so the project works end-to-end with zero setup
    and the harness/eval tests get reproducible output independent of
    model quality.

    These narratives are hand-written here, independently of
    data/ground_truth.json — the eval ground truth is never imported into
    src/. FakeLLMClient just plays the role of "a plausible LLM output,"
    which the eval step (step 4) then scores like any other.
    """

    _CANNED: dict[str, AnalysisResult] = {
        "ALERT-001": AnalysisResult(
            recommendation="escalate",
            narrative=(
                "Diego Ferreyra (CUST-1001), diseñador gráfico independiente con "
                "ingresos mensuales declarados de USD 1.200, realizó tres "
                "depósitos de efectivo en sucursal de USD 9.800, 9.700 y 9.900 "
                "en días consecutivos (22-24 de julio de 2026), por un total de "
                "USD 29.400 -- aproximadamente 24 veces sus ingresos mensuales "
                "declarados. Cada depósito se encuentra justo por debajo del "
                "umbral de USD 10.000 para el reporte de transacciones en "
                "efectivo, y la secuencia seguida, sin otra actividad en la "
                "cuenta, es consistente con una estructuración para evitar los "
                "requisitos de reporte. No hay una fuente documentada (venta de "
                "bienes, préstamo, donación) registrada para estos fondos."
            ),
            reasoning=[
                "Tres depósitos, cada uno justo por debajo del umbral de $10.000 del CTR, "
                "realizados durante tres días consecutivos -- el patrón "
                "característico de la estructuración.",
                "El monto combinado ($29.400) equivale a aproximadamente 24 veces "
                "los ingresos mensuales declarados por el cliente ($1.200), sin "
                "ninguna fuente secundaria de ingresos declarada.",
                "Todos los depósitos se realizaron en efectivo en una sucursal, "
                "evitando cualquier rastro transaccional que dejaría una "
                "transferencia bancaria o un cheque.",
                "Ninguna de las tres transacciones tiene asociado un concepto, "
                "una factura ni una contraparte."
            ],
        ),
        "ALERT-002": AnalysisResult(
            recommendation="dismiss",
            narrative=(
                "Marta Suárez (CUST-1002) es propietaria de Parrilla Suárez, "
                "un restaurante, y tiene una cuenta corriente comercial con "
                "ingresos mensuales declarados de USD 6.500. Los depósitos "
                "señalados -- USD 4.200 el 30 de julio y USD 3.900 el 1 de "
                "agosto, ambos con el concepto 'Recaudación del fin de semana' "
                "-- totalizan USD 8.100 correspondientes a un fin de semana, "
                "lo que es consistente con ingresos en efectivo provenientes "
                "de un negocio gastronómico y está en línea con el patrón "
                "histórico de depósitos de la cuenta. No hay indicadores de "
                "estructuración y los montos son proporcionales a los ingresos "
                "comerciales declarados."
            ),
            reasoning=[
                "La ocupación declarada es propietaria de un negocio "
                "gastronómico intensivo en efectivo -- los depósitos en "
                "efectivo son la forma de ingresos esperada y habitual para "
                "este perfil.",
                "Los montos de los depósitos ($4.200 y $3.900) están muy por "
                "debajo del umbral de reporte de $10.000 individualmente y "
                "también en conjunto ($8.100), sin un patrón de estructuración.",
                "El concepto 'Recaudación del fin de semana' en ambos depósitos "
                "coincide con un ciclo comercial plausible y consistente, en "
                "lugar de una suma global sin explicación.",
                "Los montos son proporcionales a los ingresos mensuales "
                "declarados por el cliente de $6.500.",
            ],
        ),
        "ALERT-003": AnalysisResult(
            recommendation="escalate",
            narrative=(
                "Lucía Bentancor (CUST-1003), arquitecta con ingresos "
                "mensuales declarados de USD 3.800, recibió una transferencia "
                "bancaria de USD 85.000 el 4 de agosto de 2026 de Inversiones "
                "Delmar SA, una contraparte en Panamá, una jurisdicción sujeta "
                "a monitoreo reforzado. El concepto indica 'Venta de propiedad "
                "- Lote 14B', lo cual es plausible para el perfil de esta "
                "cliente, pero no hay documentación respaldatoria (escritura, "
                "contrato de compraventa, registro notarial) registrada, y el "
                "nombre de la contraparte no corresponde a ningún comprador "
                "individual ni a una entidad de títulos/escrow reconocible. "
                "Dado el riesgo asociado a la jurisdicción y la ausencia de "
                "documentación que corrobore la venta inmobiliaria declarada, "
                "el caso debería escalarse a la espera de documentación en "
                "lugar de ser descartado."
            ),
            reasoning=[
                "El monto de la transferencia ($85.000) equivale a "
                "aproximadamente 22 veces los ingresos mensuales declarados, "
                "y fue recibido en una única transacción de una contraparte "
                "domiciliada en Panamá.",
                "Panamá está señalada como una jurisdicción de alto riesgo/"
                "monitoreo reforzado según la propia alerta.",
                "El propósito declarado ('venta de propiedad') es plausible "
                "para el nivel de ingresos de una arquitecta, pero no se "
                "adjunta ninguna escritura, contrato ni referencia notarial.",
                "El nombre de la contraparte parece corresponder a un vehículo "
                "de inversión genérico en lugar de a un comprador individual "
                "o una empresa de escrow/títulos, lo que es consistente con "
                "un patrón de entidad pantalla.",
            ],
        ),
        "ALERT-004": AnalysisResult(
            recommendation="escalate",
            narrative=(
                "Rodrigo Aznárez (CUST-1004) es funcionario municipal de "
                "contrataciones, una persona políticamente expuesta (PEP), "
                "con ingresos mensuales declarados de USD 1.500 y una "
                "calificación de riesgo KYC alta. El 5 de agosto de 2026, "
                "recibió una transferencia interna de USD 22.000 de 'Marisol "
                "Aznárez (hermana)', con el concepto 'Reembolso de préstamo "
                "familiar' -- aproximadamente 15 veces sus ingresos mensuales "
                "declarados. Si bien un préstamo familiar es una explicación "
                "plausible, la combinación de la condición de PEP en un cargo "
                "de contrataciones, una calificación de riesgo preexistente "
                "alta y un concepto que es una justificación común para el "
                "layering implica que el caso no puede descartarse basándose "
                "únicamente en la explicación proporcionada. Corresponde "
                "escalar el caso a la espera de documentación del préstamo "
                "subyacente."
            ),
            reasoning=[
                "El cliente es una PEP empleada en contrataciones municipales "
                "-- un cargo con una exposición elevada a riesgos de "
                "corrupción/soborno -- y ya tiene una calificación de riesgo "
                "KYC alta.",
                "El monto de la transferencia ($22.000) equivale a "
                "aproximadamente 15 veces los ingresos mensuales declarados "
                "($1.500), y fue recibido de un familiar sin un contrato de "
                "préstamo registrado.",
                "'Reembolso de préstamo familiar' es una justificación "
                "utilizada con frecuencia para realizar layering de fondos "
                "a través de la cuenta de un familiar; el concepto por sí "
                "solo no constituye evidencia suficiente de legitimidad.",
                "No hay documentación (contrato de préstamo, historial de "
                "transferencias anteriores, origen de los fondos de la "
                "hermana) que corrobore el propósito declarado.",
            ],
        ),
        "ALERT-005": AnalysisResult(
            recommendation="escalate",
            narrative=(
                "Bruno Kalix (CUST-1005), desempleado y sin ingresos "
                "declarados, tiene una cuenta corriente personal que "
                "anteriormente estaba inactiva. El 6 de agosto de 2026, la "
                "cuenta recibió una transferencia bancaria de USD 48.000 de "
                "Global Trade Partners LLC (Panamá), con el concepto "
                "'Servicios de consultoría', y ese mismo día transfirió "
                "USD 46.500 a Yuen Textiles Ltd (Hong Kong), con el concepto "
                "'Pago de factura'. El cliente no tiene ingresos ni ocupación "
                "declarados que sean consistentes con servicios de consultoría "
                "internacional, las dos contrapartes pertenecen a "
                "jurisdicciones e industrias no relacionadas, sin una relación "
                "comercial evidente entre sí ni con el cliente, y los fondos "
                "pasaron por la cuenta en un plazo de 24 horas, reteniendo "
                "únicamente USD 1.500 (~3%). Este es un patrón clásico de "
                "cuenta de paso/intermediario y debería escalarse."
            ),
            reasoning=[
                "El cliente no tiene ingresos ni ocupación declarados que "
                "expliquen la recepción de USD 48.000 por servicios de "
                "consultoría internacional.",
                "La cuenta estaba inactiva antes de esta actividad -- un "
                "ingreso repentino de gran valor en una cuenta que, por lo "
                "demás, estaba inactiva constituye en sí mismo una señal de "
                "alerta.",
                "Los fondos entrantes (USD 48.000) y salientes (USD 46.500) "
                "se produjeron el mismo día calendario, reteniendo solo "
                "~3% del monto entrante -- consistente con una cuenta de "
                "paso.",
                "La contraparte entrante (Panamá, 'servicios de consultoría') "
                "y la contraparte saliente (Hong Kong, 'pago de factura') "
                "no están relacionadas en cuanto a jurisdicción ni propósito "
                "declarado, sin un vínculo comercial discernible.",
            ],
        ),
        "ALERT-006": AnalysisResult(
            recommendation="dismiss",
            narrative=(
                "Elena Ríos (CUST-1006) es una jubilada, ex docente de "
                "escuela pública, que recibe un depósito mensual de pensión "
                "constante de USD 900 (1 de junio y 1 de julio de 2026). El "
                "2 de agosto de 2026, la cuenta recibió una transferencia "
                "bancaria de USD 62.000 de Escribanía Notarial Ríos-Bianchi, "
                "una escribanía, con el concepto 'Venta de propiedad en Av. "
                "Rivadavia 4820, escritura archivada'. En Argentina, las "
                "operaciones de compraventa de inmuebles se procesan "
                "habitualmente a través de una escribanía, y el concepto "
                "hace referencia a una escritura específica y verificable. "
                "Se trata de un hecho documentado, único y explicable que se "
                "suma a un patrón estable de depósitos de pensión, no de una "
                "anomalía de comportamiento -- se recomienda descartar la "
                "alerta."
            ),
            reasoning=[
                "Los depósitos recurrentes de USD 900 coinciden exactamente "
                "con el perfil declarado de jubilada/pensionada, sin ninguna "
                "anomalía de volumen en la actividad habitual de la cuenta.",
                "El único ingreso de gran valor ($62.000) proviene de una "
                "escribanía identificada, el canal estándar y esperado para "
                "una compraventa de inmuebles en Argentina.",
                "El concepto de la transacción hace referencia a una "
                "dirección específica de una propiedad y a una escritura "
                "archivada, proporcionando un rastro documental verificable.",
                "No hay indicadores de estructuración, transferencia rápida "
                "de fondos ni desajuste con los ingresos declarados asociados "
                "al ingreso extraordinario de una sola vez.",
            ],
        ),
        "ALERT-007": AnalysisResult(
            recommendation="dismiss",
            narrative=(
                "El 10 de agosto de 2026, Antonio Weisz recibió una "
                "transferencia bancaria entrante de USD 145.000 de "
                "Pan-Atlantic Life Assurance S.A. (Panamá), una jurisdicción "
                "incluida en la lista de monitoreo reforzado. Considerado de "
                "forma aislada, el monto equivale aproximadamente a 132 veces "
                "sus ingresos mensuales declarados de USD 1.100 como jubilado "
                "y ex ingeniero civil, y no tiene registrada ninguna relación "
                "previa con el remitente -- un patrón que normalmente "
                "justificaría una escalada. Sin embargo, el concepto de la "
                "transacción incluye un número de póliza específico "
                "(PLA-88421) y un número de reclamo (CLM-2026-0714) que "
                "identifican el pago como una indemnización por fallecimiento "
                "de un seguro de vida a un beneficiario identificado, y "
                "señala que la aseguradora está autorizada y regulada por la "
                "Superintendencia de Seguros y Reaseguros de Panamá. A "
                "diferencia de una venta de propiedad no verificada o de un "
                "supuesto préstamo familiar, el pago de una indemnización por "
                "fallecimiento por parte de una aseguradora identificada y "
                "regulada, con referencias específicas de póliza y reclamo, "
                "puede verificarse de forma independiente y no corresponde a "
                "una tipología habitualmente utilizada para realizar "
                "layering de fondos ilícitos. La diferencia entre el monto y "
                "los ingresos declarados se explica por la naturaleza del "
                "pago, no por una actividad no declarada. Se recomienda "
                "descartar la alerta, dada la solidez de la documentación "
                "registrada."
            ),
            reasoning=[
                "La transferencia bancaria de USD 145.000 del 10 de agosto "
                "de 2026 equivale a aproximadamente 132 veces los ingresos "
                "mensuales declarados por el cliente de USD 1.100 y se "
                "origina en una jurisdicción incluida en la lista de "
                "monitoreo reforzado -- indicadores superficiales que "
                "normalmente justificarían una escalada.",
                "La transacción incluye un número de póliza específico "
                "(PLA-88421) y un número de reclamo (CLM-2026-0714), "
                "identificándola como una indemnización por fallecimiento "
                "de un seguro de vida y no como una transferencia sin "
                "explicación.",
                "Se indica que el remitente, Pan-Atlantic Life Assurance "
                "S.A., está autorizado y regulado por el organismo "
                "regulador de seguros de Panamá -- una institución "
                "identificada y autorizada, no una entidad genérica o con "
                "apariencia de empresa pantalla.",
                "Un pago documentado de una indemnización por fallecimiento "
                "a un beneficiario identificado puede verificarse de forma "
                "independiente con la aseguradora y mediante los números de "
                "póliza y reclamo, lo que lo distingue de tipologías (por "
                "ejemplo, supuestas 'ventas de propiedades' o 'préstamos "
                "familiares' sin documentación) que carecen de cualquier "
                "punto de referencia externo.",
            ],
        ),
    }

    def analyze(self, alert: AlertData) -> AnalysisResult:
        try:
            return self._CANNED[alert.alert_id]
        except KeyError as exc:
            raise KeyError(
                f"FakeLLMClient has no canned response for "
                f"alert_id={alert.alert_id!r}. FakeLLMClient only covers "
                "the example alerts in data/alerts.json -- add a canned "
                "response there, or use LLM_MODE=real."
            ) from exc


def get_llm_client(mode: str | None = None) -> LLMClient:
    """Factory: returns the LLM backend selected by LLM_MODE (or the
    explicit `mode` override, mainly for tests). Fails fast and loudly on
    an unrecognized mode rather than silently defaulting.
    """
    resolved_mode = mode if mode is not None else os.environ.get("LLM_MODE", "fake")
    if resolved_mode == "fake":
        return FakeLLMClient()
    if resolved_mode == "real":
        # Lazy import: keeps LLM_MODE=fake (and everything that only
        # exercises it, e.g. the default test run) free of any dependency
        # on the openai package or a network call at import time. Only
        # resolving mode="real" ever touches real_llm_client.py.
        from real_llm_client import RealLLMClient

        return RealLLMClient()
    raise ValueError(f"Unknown LLM_MODE {resolved_mode!r}; expected 'fake' or 'real'.")
