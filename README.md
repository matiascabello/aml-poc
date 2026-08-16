# AML Alert Triage — Agente interno (PoC)

Prueba de concepto de un agente interno para el triage de alertas AML en una institución financiera de LATAM. Un LLM redacta el informe requerido para un **Reporte de Operación Sospechosa (ROS)** y propone una acción binaria (escalar o descartar). La decisión final es siempre humana: **ninguna acción con efectos se ejecuta sin la aprobación explícita de un analista, y ese control está garantizado por código, no por el prompt ni por la UI.**

- **Usuario:** analista de cumplimiento de una institución financiera.
- **Alcance de esta versión:** datos simulados, sin integraciones reales, corre localmente. El LLM solo genera texto (informe + recomendación); la ejecución la habilita el operador.
- **Fuera de alcance:** envío real del ROS a la UIF, integración con core bancario, autenticación/roles, persistencia en base de datos.

---

## Setup

### Requisitos

- Python 3.13+ (ver `requires-python` en `pyproject.toml`)
- [uv](https://github.com/astral-sh/uv) como gestor de paquetes.

### Instalación

```bash
# Clonar el repositorio
# Ejecutar:
uv sync
```

### Variables de entorno

| Variable | Valores | Default | Descripción |
|---|---|---|---|
| `LLM_MODE` | `fake` \| `real` | `fake` | `fake` usa un cliente determinístico (reproducible, sin red, sin costo). `real` usa la API de OpenAI. |
| `OPENAI_API_KEY` | — | — | Solo requerida si `LLM_MODE=real`. |

El flag `LLM_MODE` controla el cliente **explícitamente**, en vez de inferirlo de la presencia de una API key. Esto hace que las corridas sean reproducibles: el modo no cambia solo porque haya o no una key en el entorno.

### Correr la aplicación

```bash
uv run uvicorn api:app --reload --app-dir src
```

La UI queda disponible en `http://localhost:8000` (puerto default de uvicorn; el static se monta en `/`). La documentación interactiva de la API (Swagger, útil para probar el gate manualmente) está en `http://localhost:8000/docs`.

### Correr las evals

`src/eval.py` no expone todavía un CLI (`__main__`); se corre importando sus funciones. Desde la raíz del repo:

```bash
PYTHONPATH=src uv run python -c "
from llm_client import get_llm_client
from eval import run_eval, format_report
print(format_report(run_eval(get_llm_client())))
"
```

o, más simple, vía pytest, que ya tiene `pythonpath = [\"src\"]` configurado en `pyproject.toml`:

```bash
uv run pytest tests/test_eval.py -v
```

---

## Arquitectura del agente

El principio de diseño central: **el modelo decide qué recomendar; el código decide qué se puede ejecutar.** El LLM nunca tiene la capacidad de ejecutar una acción con efectos. Esa separación no es una convención ni una instrucción en el prompt: está impuesta por una máquina de estados en el código.

### Qué decide el modelo

- Lee los datos crudos de la alerta.
- Redacta el informe del ROS — el texto formal que ningún template puede replicar y que es el valor real del LLM en este caso.
- Propone una recomendación binaria: **escalar** (presentar el ROS) o **descartar** (cerrar la alerta), con su justificación.

El modelo **no** ejecuta acciones, **no** cambia el estado de una alerta y **no** tiene acceso a la función `execute()`. Su salida es exclusivamente texto.

### Qué garantiza el código

**Máquina de estados.** Cada alerta transita por estados bien definidos:

```
pending ──analyze──> analyzed ──approve──> approved ──execute──> executed
                         │
                         └──reject──> rejected (terminal)
```

- `pending`: alerta sin analizar. El agente todavía no revisó la alerta ni redactó el informe.
- `analyzed`: el LLM ya redactó el informe y la recomendación. Lista para la decisión del operador.
- `approved`: el analista aprobó la recomendación. Habilita la ejecución.
- `executed`: la acción se materializó (en esta PoC, la generación del ROS).
- `rejected`: el analista rechazó la recomendación. Estado terminal, sin salida.

**El gate.** La ejecución está protegida en el propio código de `execute()`:

```python
# src/execute.py
def execute(alert: TriageAlert) -> ExecutionResult:
    ensure_approved(alert)                              # gate.py — primera línea: aborta si el estado no es 'approved'
    # ... arma el ExecutionResult (ROS o cierre, simulado) ...
    alert._transition(AlertState.EXECUTED, detail=detail)  # cierra la transición, dentro de execute()
    return result
```

`ensure_approved()` (definida en `src/gate.py:17`) es la primera línea de `execute()` (`src/execute.py:31`): si el estado no es `approved`, lanza `NotApprovedError` y nada más corre. La transición a `executed` ocurre **dentro** de `execute()`, llamando directamente al mutador de estado de `TriageAlert` — no hay un método público tipo `mark_executed()` en la clase, a propósito: así no existe una puerta lateral que marque una alerta como ejecutada sin haberla ejecutado realmente.

**Por qué el control vive en código y no en el prompt ni en la UI.** Un prompt puede ignorarse; un botón deshabilitado puede saltarse. El gate no. La UI deshabilita botones solo por comodidad visual, pero eso no es el control de seguridad: la fuente de verdad es el backend. Cualquier cliente —incluido uno que no sea nuestra UI— que intente ejecutar una alerta no aprobada recibe un `409 Conflict`.

**Cómo verificarlo.** Se puede comprobar sin pasar por la UI, atacando el endpoint directamente:

```bash
# Intentar ejecutar una alerta que está en 'pending' (no aprobada):
curl -X POST http://localhost:8000/api/alerts/ALERT-001/execute
# → 409 Conflict: invalid transition

# La única vía válida es analizar y aprobar primero (execute requiere 'approved'):
curl -X POST http://localhost:8000/api/alerts/ALERT-001/analyze
curl -X POST http://localhost:8000/api/alerts/ALERT-001/approve
curl -X POST http://localhost:8000/api/alerts/ALERT-001/execute
# → 200 OK, status: executed
```

Que el `409` provenga de un `curl` —y no de la UI— es la demostración de que el control es del código: no depende de que el cliente "se porte bien".

### Endpoints

| Método | Ruta | Efecto | Estado requerido |
|---|---|---|---|
| `GET` | `/api/alerts` | Lista para la bandeja (id, resumen, status). | — |
| `GET` | `/api/alerts/{id}` | Detalle: datos crudos, informe, recomendación, status. | — |
| `POST` | `/api/alerts/{id}/analyze` | Corre el LLM, guarda el informe + recomendación. | `pending` |
| `POST` | `/api/alerts/{id}/approve` | Aprueba la recomendación. | `analyzed` |
| `POST` | `/api/alerts/{id}/reject` | Rechaza (terminal). | `analyzed` |
| `POST` | `/api/alerts/{id}/execute` | Materializa la acción aprobada. | `approved` |

Toda validación de transición vive en la máquina de estados. Los endpoints solo traducen la excepción al HTTP status correcto (`409` para transición inválida, `404` si el id no existe). Ni el endpoint ni la UI reimplementan esa validación.

**El ground truth (`data/ground_truth.json`) nunca se expone por la API.** El LLM y la UI solo ven `data/alerts.json`; el ground truth se usa exclusivamente para las evals.

---

## Interfaz

UI de dos paneles (bandeja + detalle) más una terminal de log, en HTML + CSS + JavaScript vanilla, sin build step. Tailwind y DaisyUI se cargan por CDN.

- **Bandeja (izquierda):** lista de alertas con badge de estado por color.
- **Detalle (derecha):** cuatro bloques — datos crudos, informe del ROS, recomendación + justificación, y controles de decisión.
- **Decisión del operador:** binaria, **Aprobar** o **Rechazar**. Aprobar dispara la ejecución; rechazar cierra la alerta. `execute` sigue siendo un endpoint propio (con su `ensure_approved()`), pero la UI no lo expone como botón separado.
- **Terminal de log:** registra cada transición **según la respuesta del backend**, no según lo que la UI asume. Un `pending → analyzed` exitoso y un `409 Conflict` sobre una transición inválida se ven ambos en el log — lo que la vuelve evidencia de que el estado vive en el backend.

Al abrir una alerta `pending`, la UI llama a `analyze` de forma condicional (solo si el status real es `pending`), loguea la transición y luego renderiza el detalle ya con el informe presente. El analista aterriza directo en la decisión, pero la transición `pending → analyzed` queda visible en el log.

---

## Decisiones (ADRs breves)

**Plain Python + FastAPI en vez de un framework de agentes (LangGraph).**
El caso tiene un único paso de decisión con un gate de aprobación; no hay un grafo de múltiples nodos que justifique la dependencia. Alternativa considerada: LangGraph, que aportaría orquestación de estados lista para usar. Tradeoff aceptado: escribimos la máquina de estados a mano (más código propio) a cambio de cero dependencias pesadas y control total sobre dónde vive el gate.

**`LLM_MODE` por env flag en vez de inferir por presencia de API key.**
Alternativa: usar el cliente real si hay `OPENAI_API_KEY`, `fake` si no. Tradeoff: el flag explícito es un poco más de fricción en el setup, a cambio de reproducibilidad — el modo no cambia silenciosamente según el entorno.

**El gate en la máquina de estados, no en el prompt ni en la UI.**
Alternativas: instruir al LLM para que no ejecute (frágil: los prompts se pueden eludir), o deshabilitar botones en la UI (frágil: la API queda expuesta). Tradeoff: ninguno relevante — es la opción correcta; el costo es escribir la validación explícita, que además es lo que se demuestra en la sesión.

**La transición a `executed` ocurre dentro de `execute()`, sin un método público `mark_executed()`.**
Se consideró marcar el estado como ejecutado desde el endpoint tras llamar a `execute()`. Eso abría una puerta lateral: se podía marcar "ejecutado" sin ejecutar. También se descartó deliberadamente exponer un `mark_executed()` público en `TriageAlert` (ver el docstring de `_transition` en `state_machine.py`), porque cualquier método público que alcance `executed` es, en sí mismo, una puerta lateral potencial. Tradeoff: ninguno — que la única vía a `executed` sea la línea dentro de `execute()`, después del gate, cierra la vulnerabilidad sin costo.

**Ground truth separado de lo que ve el LLM.**
`data/ground_truth.json` no se expone nunca por la API. Garantiza que las evals midan contra una verdad que el modelo no pudo ver.

**Rúbrica determinística para el informe, en vez de un LLM-judge.**
`narrative_checklist()` en `src/eval.py` verifica *presencia* de hechos (monto, fecha, perfil del cliente, contraparte) con reglas deterministas, no razonamiento. Alternativa: un LLM-judge que evalúe si el razonamiento del informe es sólido, no solo si cita los datos correctos. Tradeoff: la rúbrica determinística es reproducible y sin costo de inferencia extra, pero es un piso, no una prueba de que el razonamiento sea correcto. El LLM-judge queda para una siguiente iteración.

**Decisión binaria del operador (approve/reject), con `execute` disparado por `approve`.**
Alternativa: exponer `execute` como un cuarto botón. Tradeoff: se prioriza el modelo mental del analista (la decisión real es binaria) sobre la visibilidad del paso de ejecución en la UI. El gate se sigue demostrando a nivel API, así que no se pierde nada de la demostración.

**Excepción de transición → HTTP 409.**
Cada endpoint de `src/api.py` envuelve su llamada al harness en su propio `try/except` (`InvalidTransitionError` o `NotApprovedError` → `HTTPException(409)`), en vez de un exception handler global de FastAPI. Alternativa: un `@app.exception_handler(...)` único, más DRY. Tradeoff aceptado: con solo cuatro endpoints que mutan estado, el `try/except` local es más explícito sobre qué excepción puede ocurrir dónde; se reconsiderará si el número de endpoints crece.

**Frontend vanilla modular + Tailwind/DaisyUI por CDN.**
Alternativa: un SPA (React) con build. Tradeoff: el CDN de Tailwind está pensado para desarrollo, no producción — pero para una PoC local es el caso de uso correcto y ahorra todo el toolchain de build. En productización, pasa a un build con PostCSS. El JS se separa en módulos (`api`, `render`, `state`, `log`, `main`) con fronteras por responsabilidad, para que sea legible al pasar a tecnología.

---

## Estructura del proyecto

```
.
├── src/
│   ├── api.py              # FastAPI: endpoints y montaje de estáticos (app = FastAPI(...))
│   ├── state_machine.py    # máquina de estados (TriageAlert, transiciones, audit log)
│   ├── gate.py             # el gate: ensure_approved()
│   ├── execute.py          # la acción con efectos: execute() (llama al gate primero)
│   ├── alert_data.py       # carga y modelo de data/alerts.json
│   ├── llm_client.py       # interfaz + FakeLLMClient + get_llm_client()
│   ├── real_llm_client.py  # RealLLMClient (OpenAI)
│   └── eval.py             # grader de evals contra data/ground_truth.json
├── static/
│   ├── index.html
│   ├── css/
│   │   └── styles.css
│   └── js/
│       ├── api.js          # wrapper de fetch por endpoint
│       ├── render.js       # funciones de render puras
│       ├── state.js        # lista en memoria + helpers
│       ├── log.js          # terminal de log
│       └── main.js         # orquestador
├── data/
│   ├── alerts.json         # lo que ve el LLM
│   └── ground_truth.json   # solo para evals, nunca expuesto
├── tests/
│   └── test_*.py           # un archivo de tests por módulo de src/
├── docs/                   # documentos adicionales
├── CLAUDE.md
├── README.md
├── pyproject.toml
└── uv.lock
```

---

## Evals

Se miden dos cosas, siempre comparando contra `data/ground_truth.json` (las respuestas correctas, que el modelo nunca ve):

1. **¿Recomendó bien?** Para cada alerta, el modelo dice `escalate` (presentar el ROS) o `dismiss` (cerrar la alerta). Comparamos esa decisión contra la respuesta correcta.
2. **¿El informe cita los hechos?** Un chequeo automático verifica que el texto mencione los cuatro datos clave: monto, fecha, perfil del cliente y contraparte.

En vez de un porcentaje global de aciertos, usamos dos umbrales pass/fail, porque en AML no todos los errores pesan igual (ver más abajo):

- **`zero_fn_gate`** — cero falsos negativos: ninguna alerta realmente sospechosa puede quedar descartada. Es el umbral no negociable.
- **`discrimination_gate`** — el modelo tiene que descartar correctamente las alertas claramente inocentes, no escalar todo por las dudas.

El set son 7 alertas, etiquetadas por dificultad: `clear_suspicious` (claramente sospechosa), `clear_innocent` (claramente inocente) y `ambiguous` (zona gris).

En las tablas, la columna `outcome` usa la convención estándar de clasificación, leída así: escalar = "positivo", descartar = "negativo".

- **TP** (true positive): escaló, y correspondía escalar. ✓
- **TN** (true negative): descartó, y correspondía descartar. ✓
- **FP** (false positive): escaló, pero correspondía descartar. ✗ (falsa alarma)
- **FN** (false negative): descartó, pero correspondía escalar. ✗ (el error grave)

En ese vocabulario, `zero_fn_gate` es exactamente **recall = 100%** sobre la clase "escalar" — cero falsos negativos. `discrimination_gate` no calcula **precision** (no es esa fórmula), pero apunta al mismo problema desde el otro lado: sin él, una política degenerada de "escalar siempre" pasaría `zero_fn_gate` gratis, con recall perfecto y precision nula. Es el chequeo mínimo contra ese extremo, no una medición de precision en sí.

### Resultados con `LLM_MODE=fake` (chequeo del harness)

Esto no mide la calidad de un LLM real: el cliente `fake` es determinístico y sirve para verificar que la maquinaria de evaluación funciona y que las 7 alertas se procesan bien.

```
=== Recommendation correctness ===
alert_id    difficulty        ground_truth  predicted   outcome
ALERT-001   clear_suspicious  escalate      escalate    TP
ALERT-002   clear_innocent    dismiss       dismiss     TN
ALERT-003   ambiguous         escalate      escalate    TP
ALERT-004   ambiguous         escalate      escalate    TP
ALERT-005   clear_suspicious  escalate      escalate    TP
ALERT-006   clear_innocent    dismiss       dismiss     TN
ALERT-007   ambiguous         dismiss       dismiss     TN

[PASS] zero_fn_gate: no escalate-labeled alerts were missed
[PASS] discrimination_gate: correctly dismissed 2/2 clear_innocent alert(s)
```

En cuanto al informe redactado por el agente: las 7 alertas pasan las cuatro verificaciones (`cites_amount`, `cites_date`, `cites_customer_profile`, `cites_counterparty`).

### Resultados con `LLM_MODE=real` (OpenAI, `gpt-5.6-luna`)

```
=== Recommendation correctness ===
alert_id    difficulty        ground_truth  predicted   outcome
ALERT-001   clear_suspicious  escalate      escalate    TP
ALERT-002   clear_innocent    dismiss       escalate    FP
ALERT-003   ambiguous         escalate      escalate    TP
ALERT-004   ambiguous         escalate      escalate    TP
ALERT-005   clear_suspicious  escalate      escalate    TP
ALERT-006   clear_innocent    dismiss       dismiss     TN
ALERT-007   ambiguous         dismiss       escalate    FP

[PASS] zero_fn_gate: no escalate-labeled alerts were missed
[FAIL] discrimination_gate: correctly dismissed 1/2 clear_innocent alert(s)
```

Con respecto al informo, las 7 alertas pasan las cuatro verificaciones.

**Pasa el umbral que importa para el caso de uso.** `zero_fn_gate` da cero falsos negativos: ninguna alerta genuinamente sospechosa fue descartada. Es la propiedad no negociable, porque los dos errores no son simétricos:

- un **falso negativo** (cerrar un caso sospechoso real) es un fallo regulatorio;
- un **falso positivo** (escalar una alerta inocente) lo revisa un analista humano en minutos y no pasa de ahí, gracias al gate de aprobación descripto en la sección de arquitectura.

Dicho de otro modo: el sistema falla del lado seguro. Prefiere una falsa alarma antes que dejar pasar algo sospechoso.

**Los dos falsos positivos, revisados a mano:**

- **ALERT-002:** el informe cita los hechos correctamente (dos depósitos en efectivo por USD 8.100 en 3 días, ~1,25x el ingreso declarado, sin comprobante de venta que lo respalde) y aplica la regla explícita del prompt de escalar ante la duda genuina. Es un desacuerdo defendible con la etiqueta de ground truth, no un error factual.
- **ALERT-007:** escaló en esta corrida, pero al volver a llamar al modelo sobre la misma alerta con los mismos datos, el resultado fue `dismiss` — coincidiendo con el _ground truth_. A diferencia del cliente fake (determinístico), el modo real no es reproducible corrida a corrida en los casos ambiguos. Con solo 7 alertas y sin fijar temperatura ni seed, una sola corrida no debe leerse como una medición estable. El set cumple su función acá: ejercita el harness y expone los casos difíciles. Medir con rigor pide dos cosas distintas: más casos, para tener poder estadístico (7 no alcanzan para concluir), y control de la variabilidad del modelo (temperatura baja, seed) para que una corrida sea representativa de la siguiente.

Ver `src/eval.py` (grader) y `tests/test_eval.py` (fixtures) para el set completo y el runner.

## Limitaciones conocidas

En esta PoC, la aprobación por parte del operador lleva la alerta a un único estado terminal (`executed`), tanto si la recomendación es `escalate` como `dismiss`. La acción con efectos correspondiente se ejecuta de forma simulada (presentación del ROS o cierre de la alerta), pero el modelo de estados no distingue entre una alerta escalada (reporte presentado a la UIF) y una descartada (cerrada con su justificación). En un producto real, una alerta descartada debe cerrarse con su justificación y conservarse para auditoría —nunca eliminarse—, ya que los reguladores auditan precisamente las decisiones de descarte; y una alerta escalada tendría su propio ciclo (reporte presentado, en revisión por la UIF, etc.). Estados diferenciados de cierre y el ciclo de vida del reporte quedan para la siguiente iteración.

## Documentación adicional

- [Sesión en crudo de intercambios con Claude Code](/docs/20260816.md)
- [3 momentos clave del workflow de desarrollo con Claude](/docs/ai-exchanges.md)
- [PRD](/docs/prd.md)

No relacionadas con el ejercicio, pero evidencia de mi experiencia con los frameworks de orquestación de agentes CrewAI y LangGraph.

- [Agent Crew Studio](https://github.com/matiascabello/agent-crew-studio): un grupo de agentes que emulan a un equipo real de desarrollo (producto, tech lead, backend engineer, frontend engineer y testing). Le tirás una idea y te arma una PoC.
- [Should we build it?](https://github.com/matiascabello/should-we-build-it): una herramienta que ayuda a determinar si una feature o un producto deberían ser implementados o no. Dos agentes debaten sobre el tema apoyándose en la documentación compartida por el usuario y en información que puedan encontrar en la web, un tercero hace un fact-check de los argumentos de los agentes anteriores y un cuarto agente define. Es básicamente un Go/No-Go de discovery armado con agentes.

No relacionado con IA ni con la industria de Bankingly en particular, pero sí con una parte fundamental de un producto que debe analizar y clasificar un set de datos, como el desarrollado para esta PoC. Durante el desarrollo de [Scout Audit](https://github.com/CoinFabrik/scout-audit) —analizador estático de código que lideré en CoinFabrik— medir la precisión de la herramienta era fundamental para refinar la calidad de los detectores. A lo largo de todo el desarrollo llevamos a cabo sucesivos análisis de _precision and recall_ que nos daban información clave para ajustar su confiabilidad. Lo hacíamos de dos formas distintas:

- A partir de un set de datos conocido: el _ground truth_ contra el cual comparábamos los resultados arrojados por Scout Audit.
- A partir de los resultados obtenidos al correr la herramienta sobre código desconocido, que luego eran analizados por un auditor de seguridad: un trabajo mucho más exploratorio y artesanal, pero que nos permitió incorporar casos muy valiosos y mejorar considerablemente la precisión de la herramienta.

Los dos enfoques son complementarios: el _ground truth_ da una medición reproducible; el loop con el auditor es lo que realmente sube la calidad. Es exactamente el segundo paso que, en esta PoC, señalo como pendiente en la sección de Evals.
