// In-memory client-side mirror of the backend's alerts. Just a Map plus
// plain accessor functions -- no DOM, no network, no reactive system.
// The backend remains the source of truth; this only avoids refetching
// the whole inbox after every action.

const alerts = new Map(); // alert_id -> last-known object (list-item or detail shape)
let selectedId = null;

// List items (GET /api/alerts) carry alert_id at the top level; detail
// objects (GET/POST .../{id}) nest it under `alert`. Both shapes are
// handled uniformly so callers never need to know which one they have.
function idOf(item) {
  return item.alert_id ?? item.alert?.alert_id;
}

export function setAlerts(list) {
  alerts.clear();
  for (const item of list) alerts.set(idOf(item), item);
}

export function updateAlert(item) {
  alerts.set(idOf(item), item);
}

export function getAlert(id) {
  return alerts.get(id);
}

export function getAlerts() {
  return Array.from(alerts.values());
}

export function setSelected(id) {
  selectedId = id;
}

export function getSelectedId() {
  return selectedId;
}
