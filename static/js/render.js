// Pure render functions: take data, update the DOM. No fetch calls in
// this module -- api.js owns the network, this module only ever draws
// what it's handed.
//
// No component library (DaisyUI removed) -- every class here is a bare
// Tailwind utility against the palette/fonts configured in index.html's
// inline tailwind.config, shared with should-we-build-it/ui.

// Shared building blocks, so every card/title in this file stays
// visually identical without repeating the same class string everywhere.
const CARD = "bg-white border border-line rounded-xl p-4";
const CARD_TITLE = "font-mono text-xs uppercase tracking-[0.15em] text-inkSoft mb-2";
const PILL = "inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-mono uppercase tracking-wide";

// Status -> pill color. Soft tints for the four in-flight/terminal-ish
// states, solid ink for "executed" -- the one truly final state gets the
// heaviest, most "stamped" treatment instead of another tint.
const STATUS_BADGE = {
  pending: "bg-gold/10 text-gold",
  analyzed: "bg-slateBlue/10 text-slateBlue",
  approved: "bg-teal/10 text-teal",
  rejected: "bg-rust/10 text-rust",
  executed: "bg-ink text-paper",
};

// Display-only labels for the workflow states -- the underlying values
// (item.status, used as dict keys and shown verbatim in the log
// terminal) stay the English state-machine identifiers from
// state_machine.py; this map is purely what the operator reads.
const STATUS_LABEL = {
  pending: "Pendiente",
  analyzed: "Analizada",
  approved: "Aprobada",
  rejected: "Rechazada",
  executed: "Ejecutada",
};

// Same idea for the recommendation literal ("escalate"/"dismiss") the
// backend returns -- AnalysisResult.recommendation keeps the English
// value the code and CLAUDE.md's canonical vocabulary use; this is only
// the operator-facing label. escalate reads as risk (rust), dismiss as
// cleared (teal) -- same danger/safe convention as the status pills.
const RECOMMENDATION_BADGE = {
  escalate: "bg-rust/10 text-rust",
  dismiss: "bg-teal/10 text-teal",
};

const RECOMMENDATION_LABEL = {
  escalate: "Escalar",
  dismiss: "Descartar",
};

// Same idea, for the closed set of transaction type/channel codes in
// data/alerts.json -- display labels only, the underlying values are
// unaffected.
const TX_TYPE_LABEL = {
  wire_in: "Transferencia entrante",
  wire_out: "Transferencia saliente",
  cash_deposit: "Depósito en efectivo",
  internal_transfer: "Transferencia interna",
};

const CHANNEL_LABEL = {
  wire: "Transferencia bancaria",
  branch_cash: "Efectivo en sucursal",
  online: "Banca en línea",
};

const RISK_LABEL = {
  low: "Bajo",
  medium: "Medio",
  high: "Alto",
};

function idOf(item) {
  return item.alert_id ?? item.alert?.alert_id;
}

function summaryOf(item) {
  if (item.summary) return item.summary;
  if (item.alert) return `${item.alert.customer.full_name} — ${item.alert.red_flag.code}`;
  return idOf(item);
}

function money(amount) {
  // "USD 9.800": explicit currency code (a bare "$" is ambiguous across
  // LATAM currencies) and the region's period-thousands convention --
  // matches how the LLM narrative writes the same figures.
  return amount == null ? "—" : `USD ${amount.toLocaleString("es-AR")}`;
}

export function renderBadge(status) {
  const cls = STATUS_BADGE[status] || "bg-inkSoft/10 text-inkSoft";
  return `<span class="${PILL} ${cls}">${STATUS_LABEL[status] || status}</span>`;
}

export function renderInbox(alerts, selectedId) {
  const container = document.getElementById("inbox-list");
  container.innerHTML = alerts
    .map((item) => {
      const id = idOf(item);
      const active = id === selectedId ? "bg-paper" : "";
      return `
        <li>
          <button type="button" data-id="${id}" class="alert-row w-full text-left px-4 py-3 flex items-center justify-between gap-3 hover:bg-paper ${active}">
            <span class="flex flex-col overflow-hidden">
              <span class="font-mono text-xs text-inkSoft">${id}</span>
              <span class="text-sm truncate">${summaryOf(item)}</span>
            </span>
            ${renderBadge(item.status)}
          </button>
        </li>`;
    })
    .join("");
}

export function renderEmptyDetail() {
  document.getElementById("detail-panel").innerHTML = `
    <div class="p-8 text-inkSoft text-center">Seleccione una alerta de la bandeja para revisarla.</div>`;
}

export function renderDetailLoading(alertId) {
  document.getElementById("detail-panel").innerHTML = `
    <div class="flex items-center gap-3 text-inkSoft p-8">
      <span class="inline-block w-4 h-4 border-2 border-line border-t-ink rounded-full animate-spin"></span>
      <span>Analizando ${alertId}…</span>
    </div>`;
}

function renderActions(id, status) {
  if (status !== "analyzed") {
    const note =
      status === "pending"
        ? "Pendiente de análisis."
        : `Estado terminal (${STATUS_LABEL[status] || status}) — no hay más acciones disponibles.`;
    return `
      <div class="${CARD}">
        <h3 class="${CARD_TITLE}">Acción del Operador</h3>
        <p class="text-sm text-inkSoft">${note}</p>
      </div>`;
  }
  return `
    <div class="${CARD}">
      <h3 class="${CARD_TITLE}">Acción del Operador</h3>
      <div class="flex gap-3">
        <button type="button" data-id="${id}" class="approve-btn bg-teal text-paper px-4 py-2 rounded-md font-mono text-xs uppercase tracking-wide hover:bg-teal/90 transition-colors">Aprobar</button>
        <button type="button" data-id="${id}" class="reject-btn border border-rust text-rust px-4 py-2 rounded-md font-mono text-xs uppercase tracking-wide hover:bg-rust hover:text-paper transition-colors">Rechazar</button>
      </div>
    </div>`;
}

export function renderDetail(detail) {
  const id = idOf(detail);
  const { alert, analysis, status } = detail;

  const txRows = alert.transactions
    .map(
      (tx) => `
        <tr>
          <td class="font-mono text-xs py-1.5 pr-2">${tx.tx_id}</td>
          <td class="py-1.5 pr-2">${tx.date}</td>
          <td class="py-1.5 pr-2">${TX_TYPE_LABEL[tx.type] || tx.type}</td>
          <td class="text-right py-1.5 pr-2">${money(tx.amount_usd)}</td>
          <td class="py-1.5 pr-2">${CHANNEL_LABEL[tx.channel] || tx.channel}</td>
          <td class="py-1.5 pr-2">${tx.counterparty_name ?? "—"}${tx.counterparty_relationship ? ` (${tx.counterparty_relationship})` : ""}</td>
          <td class="py-1.5">${tx.counterparty_country ?? "—"}</td>
        </tr>`
    )
    .join("");

  const analysisBlock = analysis
    ? `
    <div class="${CARD}">
      <h3 class="${CARD_TITLE}">Informe del ROS (LLM)</h3>
      <p class="whitespace-pre-wrap text-sm leading-relaxed">${analysis.narrative}</p>
    </div>
    <div class="${CARD}">
      <h3 class="${CARD_TITLE}">Recomendación y Justificación</h3>
      <span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-mono uppercase tracking-wide w-fit ${RECOMMENDATION_BADGE[analysis.recommendation] || "bg-inkSoft/10 text-inkSoft"}">${RECOMMENDATION_LABEL[analysis.recommendation] || analysis.recommendation}</span>
      <ul class="list-disc list-inside text-sm space-y-1 mt-2">
        ${analysis.reasoning.map((r) => `<li>${r}</li>`).join("")}
      </ul>
    </div>`
    : `
    <div class="${CARD} text-inkSoft text-sm">Sin análisis todavía.</div>`;

  document.getElementById("detail-panel").innerHTML = `
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-semibold font-mono">${id}</h2>
      ${renderBadge(status)}
    </div>
    <div class="grid gap-4">
      <div class="${CARD}">
        <h3 class="${CARD_TITLE}">Datos de la Alerta</h3>
        <dl class="grid grid-cols-2 gap-x-4 gap-y-1 text-sm mb-3">
          <dt class="text-inkSoft">Cliente</dt><dd>${alert.customer.full_name} (${alert.customer.customer_id})</dd>
          <dt class="text-inkSoft">Ocupación</dt><dd>${alert.customer.declared_occupation}</dd>
          <dt class="text-inkSoft">Ingreso mensual declarado</dt><dd>${money(alert.customer.declared_monthly_income_usd)}</dd>
          <dt class="text-inkSoft">Calificación de riesgo</dt><dd>${RISK_LABEL[alert.customer.risk_rating] || alert.customer.risk_rating}${alert.customer.is_pep ? " · PEP" : ""}</dd>
          <dt class="text-inkSoft">Red flag</dt><dd>${alert.red_flag.code} — ${alert.red_flag.description}</dd>
          <dt class="text-inkSoft">Fecha de detección</dt><dd>${alert.flagged_at}</dd>
        </dl>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-line text-inkSoft text-xs uppercase tracking-wide">
                <th class="text-left font-medium py-1.5 pr-2">Tx</th>
                <th class="text-left font-medium py-1.5 pr-2">Fecha</th>
                <th class="text-left font-medium py-1.5 pr-2">Tipo</th>
                <th class="text-right font-medium py-1.5 pr-2">Monto</th>
                <th class="text-left font-medium py-1.5 pr-2">Canal</th>
                <th class="text-left font-medium py-1.5 pr-2">Contraparte</th>
                <th class="text-left font-medium py-1.5">País</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">${txRows}</tbody>
          </table>
        </div>
      </div>
      ${analysisBlock}
      ${renderActions(id, status)}
    </div>`;
}
