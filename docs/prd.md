# PRD — Triage de Alertas AML (Agente Interno)

**De PoC a producto.** Este documento parte del PoC ya construido (ver `README.md` para arquitectura y `CLAUDE.md` para el brief original) y lo cierra como definición de producto.

---

## 1. Elección

**Caso elegido:** un agente interno que asiste al analista de cumplimiento de una institución financiera LATAM en el triage de alertas AML (Anti-Money Laundering), redactando el informe de un **ROS** (Reporte de Operación Sospechosa) y proponiendo reportar el caso o descartarlo.

**Por qué este caso:**
- **El LLM resuelve algo que un template no puede.** Los reguladores LATAM (UIF / marco GAFILAT, alineado a GAFI/FATF) exigen que el ROS incluya un informe razonado y específico — citando montos, fechas y cómo la actividad se aparta del perfil declarado — no una alerta genérica. Redactar eso sobre evidencia heterogénea (transacciones vs. perfil KYC vs. jurisdicción) es exactamente lo que un LLM hace bien y un template no.
- **El costo de no automatizarlo es real y medible.** Cada alerta hoy consume tiempo de redacción manual de un analista calificado; el volumen de alertas escala con el negocio, el headcount de compliance no escala igual de rápido.
- **El riesgo del dominio calza con la restricción central del ejercicio.** En AML, un falso negativo (una alerta genuinamente sospechosa que se cierra sin revisión humana) es una falla regulatoria, no solo un bug. Que el código —no el prompt ni la UI— sea quien garantice que ninguna acción se ejecuta sin aprobación explícita no es una restricción arbitraria del ejercicio: es exactamente la propiedad que este dominio necesita.

---

## 2. Usuarios

| Usuario | Rol en el producto | En esta versión |
|---|---|---|
| **Analista de cumplimiento** (primario) | Revisa el informe + recomendación del agente, aprueba o rechaza. | Sí — es quien opera la UI. |
| **Oficial de cumplimiento / supervisor** | Audita decisiones, necesita trazabilidad y métricas de calidad del triage agregadas. | No — solo el audit log por alerta existe; sin vista agregada. |
| **UIF (regulador)** | Recibe el ROS una vez presentado. | No es usuario del sistema — no hay integración de envío. |

---

## 3. Alcance de esta versión

Ya construido (PoC funcional, end-to-end):
- Máquina de estados con gate de aprobación no evitable por código (`pending → analyzed → approved → executed`, `rejected` terminal).
- LLM intercambiable (`LLM_MODE=fake|real`) — informe + recomendación en español, formato LATAM (fecha día-primero, punto de miles).
- UI de bandeja + detalle + decisión binaria (Aprobar/Rechazar).
- Evals: corrección de recomendación contra ground truth (con gates, no un % agregado) + calidad de informe (rúbrica de presencia de evidencia).

Explícitamente fuera de alcance (documentado también en el README):
- Envío real del ROS a la UIF.
- Integración con core bancario o con el sistema de monitoreo transaccional real (los datos son simulados).
- Autenticación/roles.
- Persistencia en base de datos (el estado vive en memoria del proceso).

---

## 4. Requisitos priorizados

**P0: ya construido, es el corazón del producto:**

1. Gate de aprobación garantizado por código, no por prompt ni UI.
2. Informe ROS-ready en español con evidencia citada (monto, fecha, perfil).
3. Recomendación binaria (escalar/descartar) con justificación.
4. Audit log de cada transición, con timestamp.
5. Evals reproducibles con umbral pass/fail, no un % vanidoso.

**P1: siguiente iteración, condición para probar con datos reales:**

6. Persistencia (hoy el estado se pierde al reiniciar el proceso — inaceptable para un sistema que audita decisiones regulatorias).
7. Autenticación/roles (analista vs. supervisor).
8. Estados diferenciados de cierre — hoy `executed` no distingue "ROS presentado, en revisión de la UIF" de "alerta descartada, archivada" (limitación ya señalada en el README).
9. Exportación de auditoría para el regulador/supervisor.

**P2: roadmap, no bloquea el piloto:**

10. Integración real de envío del ROS a la UIF.
11. Integración con el sistema de monitoreo transaccional real.
12. LLM-judge para calidad de razonamiento (hoy la rúbrica solo verifica presencia de hechos, no que el razonamiento sea sólido — ADR ya registrado en el README).

---

## 5. Criterios de aceptación

- **Cero excepciones al gate:** ninguna alerta alcanza `executed` sin pasar por `approved` — verificado por tests automatizados y por ataque directo al endpoint (`curl`), no solo por la UI.
- **`zero_fn_gate` en 0 (recall = 100% sobre la clase "escalar"):** ninguna alerta genuinamente sospechosa del set de evaluación es recomendada como `dismiss`. No negociable — es el criterio que refleja la asimetría de riesgo regulatorio.
- **100% de las narrativas en español**, con formato LATAM (fecha día-primero, punto de miles), verificado por la rúbrica de evals.
- **100% de las narrativas citan** monto, fecha y perfil del cliente cuando esa evidencia está presente en la alerta.
- **100% de las transiciones de estado** quedan en el audit log, con timestamp y detalle.

---

## 6. Cierre de producto

### Visión a 12 meses
El agente deja de ser un asistente de redacción y se convierte en la primera línea de triage de AML para instituciones financieras LATAM: cada alerta que entra al sistema de monitoreo llega al analista ya con narrativa y recomendación redactadas, dejando al humano el 100% del poder de decisión pero liberándolo de la redacción. El éxito se mide en tiempo de triage por alerta y en tasa de acuerdo entre la recomendación del agente y la decisión final del analista — no en reemplazar al analista, sino en que deje de ser cuello de botella cuando el volumen de alertas crece.

### Roadmap en 3 etapas

| Etapa | Horizonte | Foco |
|---|---|---|
| **1 — Hardening** | 0–3 meses | Persistencia, auth/roles, estados diferenciados de cierre. Piloto en **modo shadow**: el agente corre en paralelo sobre alertas reales, el analista sigue decidiendo por su cuenta; se mide acuerdo agente-humano sin que el agente influya en la decisión todavía. |
| **2 — Piloto asistido** | 3–6 meses | 1–2 instituciones, analistas reales aprobando/rechazando sobre la recomendación del agente. Auditoría exportable para el supervisor. |
| **3 — Escalar** | 6–12 meses | Integración con el flujo real de generación/envío del ROS (aprobación humana sigue siendo obligatoria), expansión a más instituciones, LLM-judge para razonamiento. |

### Esqueleto de business case
- **Costo:** horas de analista hoy dedicadas a redactar narrativas manualmente (a levantar con el cliente) vs. costo de inferencia del LLM — bajo, dado que el modelo usado (`gpt-5.6-luna`) es el tier económico de OpenAI. A esto se suma el costo de engineering de las etapas P1 (persistencia, auth).
- **Valor:** reducción del tiempo de triage por alerta, mayor consistencia y calidad de la narrativa (menor riesgo de que la UIF rechace un ROS por narrativa genérica), capacidad de absorber crecimiento en volumen de alertas sin escalar headcount 1:1.
- **Riesgo evitado:** menor exposición a sanción regulatoria por narrativas deficientes o por alertas mal cerradas y sin trazabilidad — hoy el sistema deja un audit log de cada decisión, humana y del agente.

### Riesgos

| Riesgo | Mitigación |
|---|---|
| Dependencia de la calidad del LLM para un documento regulatorio | El humano aprueba siempre; evals con gates específicos (no un % agregado); audit log completo. |
| El prompt indica "ante la duda, escalar" — prioriza recall sobre precision, genera falsos positivos | Aceptado a propósito: el costo asimétrico (un FN es una falla regulatoria, un FP es una revisión humana de minutos) hace que priorizar recall sea el tradeoff correcto para este dominio. Confirmado en la corrida real de evals: 2 FP sobre 7, 0 FN — recall = 100%, precision más baja, exactamente el punto de operación buscado. |
| `LLM_MODE=real` no es reproducible corrida a corrida (confirmado en evals: una misma alerta dio resultados distintos en dos llamadas independientes) | No leer una corrida puntual de evals como medición estable. Antes del piloto (Etapa 2), invertir en medición más sofisticada que una corrida única: múltiples muestras por alerta (self-consistency / majority vote, no solo N=1) para reportar variancia además del resultado puntual, fijar temperatura/seed donde la API lo permita para acotar la variabilidad, y ampliar el set de evaluación a un tamaño donde la tasa de acuerdo agente-humano tenga significancia estadística real. En producción, monitorear esa tasa de forma continua, no solo contra el set fijo de evals. |
| Dependencia de un único proveedor (OpenAI) | Ya mitigado por diseño: `LLMClient` es una interfaz intercambiable, probada con el propio patrón fake/real. |
| Datos de clientes (PII, datos financieros) viajan a un proveedor externo vía API | Pendiente antes de producción con datos reales: revisión legal/DPA y evaluación de residencia de datos. Bloqueante para el Go de producción, no para el piloto en modo shadow con datos simulados. |

### Go/No-Go, con criterios de reversión

**Go (para pasar de Etapa 1 a Etapa 2, piloto asistido):**
- `zero_fn_gate` en 0 (recall = 100% sobre la clase "escalar") sobre un set de evaluación ampliado y representativo (no las 7 alertas de ejemplo — un set etiquetado por compliance, con volumen estadísticamente significativo), medido con múltiples muestras por alerta y no una corrida única, dado el no-determinismo ya confirmado de `LLM_MODE=real`.
- Tasa de acuerdo agente-humano ≥ umbral a definir con el equipo de cumplimiento sobre el piloto en modo shadow.
- Revisión legal/DPA del envío de datos a OpenAI completada y aprobada.

**No-Go / reversión:**
- Si el modo shadow (Etapa 1) muestra **cualquier** falso negativo confirmado sobre el set ampliado, el piloto no avanza a Etapa 2 hasta ajustar prompt/modelo y re-validar.
- Reversión operativa disponible en cualquier momento: el equipo de cumplimiento puede suspender el agente por completo y volver a un proceso 100% manual (el analista redacta la narrativa desde cero, como antes del agente) sin perder funcionalidad del resto del sistema — la máquina de estados y el gate de aprobación no dependen del LLM para funcionar. `LLM_MODE=fake` no es una alternativa de reversión: es un modo de testing/demo con narrativas canned que no corresponden a la alerta real, y no tiene ningún lugar en producción.
