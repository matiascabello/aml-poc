# Intercambios con IA

Anexo a `docs/case.md` (Parte 2): los tres momentos mínimos requeridos —
copiados tal cual, sin editar ni resumir — con su ubicación exacta en el
export completo de la sesión de Claude Code: **[`20260816.md`](./20260816.md)**
(adjuntado sin editar, tal como permite el enunciado cuando la herramienta
exporta la sesión completa).

Los fragmentos de abajo son citas literales de ese archivo. Los cortes de
línea a mitad de palabra (p. ej. "ru-n") son el formato original de la
captura de terminal exportada, no un error de esta transcripción.

Todos los intercambios con Claude están en inglés dado que es el idioma que uso para interacturar con la herramienta.

---

## (a) El prompt que produjo la pieza más importante del prototipo

`20260816.md:675–729`

El gate no salió cerrado desde el primer pedido de la máquina de estados:
al terminar el harness inicial, el propio modelo señaló un hueco —
`mark_executed()` era un método público invocable directamente, sin pasar
por `execute()` ni por el gate—. El prompt que sigue es el que cierra ese
hueco y produce la garantía que después el README describe como el
requisito central del ejercicio ("el control garantizado por el código, no
por el prompt").

Lo que el modelo señaló, antes del prompt:

```
One more thing worth noting: mark_executed() on TriageAlert is a state-machine
primitive, not the lock itself — nothing stops something else from calling it
directly and lying about having filed a ROS. The audit log would still show
it happened, but the guarantee in CLAUDE.md is specifically about execute(),
the function that performs the effectful action — and that one is airtight. If
you want mark_executed() itself un-callable except from within execute(),
that's a small follow-up (e.g. a private convention or moving the transition
inline into execute()); I left it as a visible method for testability and
audit-log clarity, but flag if you'd rather tighten it now before we move to
step 3.

✻ Cogitated for 2m 45s
```

El prompt (verbatim):

```
❯ Yes, move the transition to executed INSIDE execute(), after the gate check,
  so there's no public primitive that can reach the executed state
  independently. The only path to executed MUST go through ensure_approved().
  Keep the audit log working
```

Lo que produjo (diff verbatim sobre `src/state_machine.py`):

```
⏺ Now removing the public mark_executed() primitive:

⏺ Update(src/state_machine.py)  ⎿  Added 7 lines, removed 7 lines
    78      def reject(self, reason: str | None = None) -> None:
    79          self._transition(AlertState.REJECTED, detail=reason or 
        "rejected by analyst")
    80  
    81 -    def mark_executed(self, detail: str) -> None:              
    82 -        """Called by execute() once the effectful action has ru
       -n. Not meant                                                   
    83 -        to be called by anything else — execute() is the only l
       -egitimate                                                      
    84 -        caller, since it is the only path that runs the gate ch
       -eck first.                                                     
    85 -        """                                                    
    86 -        self._transition(AlertState.EXECUTED, detail=detail)   
    87 -                                                               
    81      def _transition(self, to_state: AlertState, detail: str | N
        one = None) -> None:
    82 +        """The sole state mutator. Deliberately not exposed as 
       +a public                                                       
    83 +        `mark_executed()`-style wrapper for the executed state:
       + the only                                                      
    84 +        sanctioned path to `executed` is execute() in execute.p
       +y, which                                                       
    85 +        calls this directly, after — and only after — ensure_ap
       +proved()                                                       
    86 +        passes. There is no public primitive on this class that
       + reaches                                                       
    87 +        `executed` on its own.                                 
    88 +        """                                                    
    89          allowed = ALLOWED_TRANSITIONS[self.state]
    90          if to_state not in allowed:
    91              raise InvalidTransitionError(
```

Esta es exactamente la propiedad que hoy verifica `grep -rn "mark_executed"`
(cero resultados fuera del docstring) y que la sección "Arquitectura del
agente" del README describe.

---

## (b) El intercambio donde el modelo devolvió algo incorrecto y cómo se detectó

`20260816.md:1901–1998` y `2349–2378`

Al llegar el checkpoint de revisión de la Parte (c) de abajo, se le pidió al
modelo verificar explícitamente todo antes de escribir código. Verificando,
encontró que una suposición ya presente en el código de pasos anteriores
—un test que esperaba `pytest.raises(ValueError)` al migrar `AnalysisResult`
a Pydantic— era incorrecta: `pydantic.ValidationError` no es subclase de
`ValueError` en Pydantic v2. Es el propio proceso de verificación (búsqueda
web, no la memoria del modelo) el que detecta el error antes de que se
propague al código nuevo.

```
⏺ Web Search("pydantic v2 ValidationError subclass ValueError inheritance")
  ⎿  Did 1 search in 6s

⏺ Web Search("pydantic latest version pypi 2026")
  ⎿  Did 1 search in 4s
⏺ Good call — I did skip that checkpoint. Here are the four things, no code
  written yet.

  1. What I verified

  - SDK version: openai 3.1.0 on PyPI (released 2026-08-14, one day before
  today). Note: v3.0.0 made HTTPX2 the default HTTP client — a breaking change,
  but only relevant if we customize the HTTP transport, which we won't.
  - Structured-output method: the current path is the Responses API,
  client.responses.parse(model=..., input=[...], text_format=<PydanticModel>).
  Not manual JSON-mode + regex, not the older chat.completions free-text path.
  Parsed result comes back at response.output_parsed; refusals/schema failures
  surface separately (need to check response.output for a refusal content item,
  not assume output_parsed is always populated).
  - Also checked: OpenAI's strict structured-outputs supports minItems/maxItems
  on arrays and enum/Literal for constrained strings on base (non-fine-tuned)
  models — relevant for point 3 below.

  Sources: PyPI openai, OpenAI structured outputs guide

  2. The model
  [...]

  3. AnalysisResult + Pydantic

  Current (step 3), verbatim from src/llm_client.py:

  @dataclass(frozen=True)
  class AnalysisResult:
      recommendation: str  # "escalate" | "dismiss"
      narrative: str
      reasoning: list[str]

      def __post_init__(self) -> None:
          if self.recommendation not in RECOMMENDATIONS:
              raise ValueError(...)

  It's a plain dataclass, not Pydantic. Proposed converged version, used
  identically by FakeLLMClient, RealLLMClient, and eval.py:

  from pydantic import BaseModel, ConfigDict, Field
  from typing import Literal

  class AnalysisResult(BaseModel):
      model_config = ConfigDict(frozen=True)

      recommendation: Literal["escalate", "dismiss"]
      narrative: str
      reasoning: list[str] = Field(min_length=3, max_length=6)

  Benefit beyond "one shared type": RealLLMClient can pass
  text_format=AnalysisResult directly to responses.parse() — no separate private
  schema class needed, response.output_parsed comes back as an AnalysisResult
  instance already.

  This does touch step-3 code — here's the exact diff surface, so you can review
  before I apply it:

  File: src/llm_client.py
  Change: AnalysisResult swaps @dataclass → BaseModel; drops the hand-rolled
  __post_init__/RECOMMENDATIONS check (replaced by the Literal type itself)
  ────────────────────────────────────────
  File: tests/test_llm_client.py
  Change: test_analysis_result_rejects_invalid_recommendation currently asserts
  pytest.raises(ValueError) — this breaks. Verified: Pydantic v2's
  ValidationError is not a subclass of ValueError (raising ValueError inside a
  validator gets wrapped into ValidationError, but the exception the caller
  actually sees is ValidationError). Test needs to catch
  pydantic.ValidationError instead.
  ────────────────────────────────────────
  File: pyproject.toml
  Change: add openai==3.1.0, pydantic==2.13.4 (current stable; there's a
  2.14.0a1
  prerelease on PyPI, deliberately not using it) to [project.dependencies]
```

La corrección aplicada, verbatim:

```
⏺ Now find and fix test_analysis_result_rejects_invalid_recommendation:

  Searched for 1 pattern (ctrl+o to expand)

⏺ Update(tests/test_llm_client.py)
  ⎿  Added 4 lines, removed 2 lines
   93  
   94  
   95  def test_analysis_result_rejects_invalid_recommendation():
   96 -    with pytest.raises(ValueError):                           
   97 -        AnalysisResult(recommendation="approve", narrative="x"
      -, reasoning=["x"])                                            
   96 +    # Pydantic v2's ValidationError is not a subclass of Value
      +Error --                                                      
   97 +    # verified before writing this, not assumed.              
   98 +    with pytest.raises(pydantic.ValidationError):             
   99 +        AnalysisResult(recommendation="approve", narrative="x"
      +, reasoning=["a", "b", "c"])                                  
  100  
  101  
  102 def test_fake_client_recommendations_match_ground_truth_fixtur
       e():

⏺ Now run the full suite:

⏺ Bash(uv run pytest -v 2>&1 | tail -90)
  ⎿  ============================= test session starts ====================
     ==========
     platform darwin -- Python 3.13.6, pytest-9.1.1, pluggy-1.6.0 -- /Users
     … +94 lines (ctrl+o to expand)
⏺ All 68 tests pass — same as predicted, only the two flagged tests changed.
```

---

## (c) El momento en que se cambió de enfoque porque la herramienta iba a un lugar equivocado

`20260816.md:1826–1893`

Al pasar a construir `RealLLMClient` (el cliente de OpenAI real), el modelo
saltó directo a instalar dependencias y empezar a implementar sin mostrar
antes el plan — pese a que se le había pedido explícitamente un checkpoint
de revisión previo. Se interrumpió la ejecución (`Interrupted`) y se
redirigió el enfoque antes de que escribiera ninguna línea de código nuevo.

```
⏺ Now let's implement. First, add the dependencies:

⏺ Bash(uv add openai pydantic 2>&1 | tail -20)
  ⎿  Interrupted · What should Claude do instead?

✻ Sautéed for 7m 30s

❯ Hold on — stop before implementing. You skipped the review checkpoint I asked 
  for: I want to see the plan before you write the client.                      

  Good that you verified versions. Before writing any code, show me these four  
  things, then STOP — don't call the real API yet:                             

  1. What you found — exact SDK version, and the structured-output method       
     (responses.parse / whatever the current API uses). One or two lines each.  

  2. The model. I want to use gpt-5.6-luna — I've been using it in other        
  projects                                                                       
     and the cost is great. But confirm the exact API model string against the  
     current OpenAI docs before writing it in, since model identifiers are easy 
  to                                                                             
     get slightly wrong. If that exact string doesn't appear in the current     
  model                                                                          
     list, tell me — don't substitute a different model silently, and don't     
  assume                                                                        
     it's right just because I said it.                                        

  3. AnalysisResult + Pydantic. Show how AnalysisResult is defined right now    
     (step 3). Use Pydantic for the structured output — it's OpenAI's standard  
     path. If AnalysisResult is already Pydantic, reuse it as the response      
  schema;                                                                       
     if it's a dataclass/plain type, converge on a single Pydantic              
  AnalysisResult                                                                
     used by the fake client, the real client, and the eval alike — one         
  validated                                                                     
     definition of the analysis shape. Flag if that conversion touches step-3   
  code                                                                          
     so I can review the diff (the 68 tests should still pass after).          

  4. The analysis prompt — the text that turns an alert into the recommendation 
  +                                                                              
     narrative. It must ask for the specific-reason + evidence-breakdown        
  narrative                                                                     
     our rubric expects (per CLAUDE.md: names the specific reason for suspicion 
  and                                                                           
     breaks down the evidence by amount/date/counterparty; not                  
  generic/defensive).                                                          
     This is the key artifact — I want to read it before any API call.         

  Requirements for when you do write it:                                       
  - Implements the exact same LLMClient interface as FakeLLMClient, returning   
  the                                                                           
    same AnalysisResult shape. The rest of the system must not know it's OpenAI 
  —                                                                             
    the provider dependency stays contained in this class only.                
  - Selected via LLM_MODE=real; needs OPENAI_API_KEY. Fake stays the default.   
  - Use structured output so the response matches the schema — if the model    
  returns                                                                       
    something off-schema, fail loudly, don't silently coerce.                  

  Show me those four things, then stop.

  Read 1 file (ctrl+o to expand)

⏺ Confirmed: AnalysisResult is currently a plain frozen dataclass, not Pydantic.
  Now let me verify gpt-5.6-luna against the official OpenAI docs directly (not
  a third-party aggregator).
```

Esta interrupción es también el origen directo del intercambio (b): la
verificación que produjo era exactamente lo que expuso el error del
`ValueError`/`ValidationError`.
