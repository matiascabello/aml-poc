# Ejercicio Técnico— Technical Product Manager (Bankingly)

## Contexto

Bankingly provee soluciones digitales a más de 100 instituciones financieras en América Latina. La dirección ejecutiva definió como apuesta estratégica la "banca agéntica": agentes con IA que ejecutan trabajo bancario real, siempre con aprobación humana. El punto de partida es un agente interno: trabaja
para el personal de la institución (riesgo, crédito, cumplimiento, cobranzas), no de cara al usuario final.
Tu rol en este ejercicio es el del puesto: recibir una directriz abierta, decidir por dónde empezar, validar con un prototipo, medir y recomendar. Si idas y vueltas: si algo es ambiguo, decidí, documentá la decisión y su tradeoff y seguí.

## Cómo funciona

- Take-home: 8 horas de trabajo estimado.
- La entrega es requisito para continuar el proceso. Sin fecha límite: considerar que valoramos la velocidad como parte del proceso.
- Después de la entrega: sesión en vivo de 30 minutos (20 de presentación + 10 de preguntas).

Parte del rol es entregar: una entrega prolija de 8 horas con recortes bien elegidos vale más que una pulida de 16. Tu código es tuyo: no lo usaremos internamente.

## Parte 1 - Elegí qué construir

Elegí UN caso de uso concreto y acotado de agente interno para una institución financiera de LATAM (ejemplos, no obligatorios: aprobación de una solicitud de crédito, revisión de alertas AML, verificación KYC, monitoreo de riesgo de cartera, cobranza temprana). Documentá la elección como primera
sección de tu PRD: problema, por qué este caso primero (impacto, esfuerzo, riesgo—incluido el regulatorio) y qué alternativas descartaste. La solución debería poder ofrecerse a decenas de instituciones, no a un solo banco.

## Parte 2 - Prototipo + medición

### A) Prototipo

Prototipo funcional del caso elegido, con datos simulados (sin integraciones reales), que corra localmente con instrucciones reproducibles.

Regla de diseño: toda acción con efectos (aprobar un crédito, cerrar una alerta, bloquear una cuenta) debe ser propuesta por el agente y aprobada por el analista humano antes de ejecutarse, con ese control garantizado por el código, no por el prompt.

En el README incluí una sección "Arquitectura del agente": qué decide el modelo y qué garantiza tu código (límites, validaciones, aprobaciones, estado). Se valora el manejo de conceptos de agent harness y plataformas de agentes.

Se valora código legible, mínimo y reproducible: las validaciones del rol pasan luego al área de tecnología para productizar.

Registrá en el README las decisiones que tomaste ante dudas o ambigüedad - estilo ADR breve: qué decidiste, qué alternativas consideraste, qué tradeoff aceptaste.

Usá herramientas de desarrollo con IA (Claude Code, Codex o equivalentes) y entregá los intercambios textuales, no un resumen: como mínimo tres momentos, copiados tal cual, en un archivo aparte del repositorio — (a) el prompt que produjo la pieza más importante del prototipo; (b) el intercambio donde
el modelo devolvió algo incorrecto y cómo lo detectaste; (c) el momento en que cam
biaste de enfoque porque la herramienta te llevaba a un lugar equivocado.

Si tu herramienta exporta la sesión completa, adjuntala sin editar. No incluyas conversaciones ajenas al ejercicio. Son minutos de copiar y pegar: no mueve el techo de 8 horas.

No evaluamos prolijidad de redacción ni prompt-craft: queremos ver cómo dirigís la herramienta y cómo verificás lo que devuelve.

B) Medición

Un set de evaluación con métrica y umbral definidos antes de medir, y resultados medidos por categoría. Tamaño a tu criterio, pero medido: un set chico con resultados vale, un plan sin resultados no alcanza. Incluí casos difíciles donde el agente falle: el análisis de errores vale más que un 100% de éxito
en casos fáciles.

Entrega: link a un repositorio Git (GitHub, GitLab u otro; púb lico o con invitación de acceso) con:

- El código y un README técnico (setup + arquitectura del agente + registro de decisiones);
- los intercambios con la IA, en el archivo aparte descrito en la Parte 2;
- un PRD breve: tu elección (Parte 1), usuarios, alcance de esta versión requisitos priorizados, criterios de aceptación, y el cierre de producto (visión a 12 meses, roadmap en 3 etapas, esqueleto de business case, riesgos, Go/No-Go con criterios de reversión);
- los resultados de evals.

### Sesión en vivo (30 min: 20 de presentación + 10 de preguntas)

Presentás y demostrás tu solución cubriendo estos puntos; son los criterios de evaluación:

1. El caso: qué elegiste, por qué, qué descartaste.
2. Demo del flujo completo, incluido qué pasa si se le pide al agente ejecutar sin apro bación y dónde vive ese control en el código.
3. Arquitectura del agente (harness): qué decide el modelo, qué garantiza tu código.
4. Medición: tus evals, qué falla, qué aprendiste de los errores.
5. Uso de IA: caminamos uno de los intercambios que entregaste. El panel elige cuál.
6. Pitch de producto, desde tu PRD: visión, roadmap, business case, riesgos y tu Go/No-Go con criterios de reversión. Sin material nuevo: defendés tu documento.
7. Decisiones y recortes: qué decidiste ante ambigüedad, qué recortaste, y los tradeoffs aceptados.

Apoyo visual libre. Las preguntas del panel van en los últimos 10 minutos.

Complemento (opcional)

Si ya construiste algo equivalente, incluí el link en la entrega. No reemplaza el ejercicio ni consume tiempo de la sesión; si aporta, lo conversamos en otra instancia del proceso.

Gracias por tu interés y por el tiempo que le dediques a esta propuesta.