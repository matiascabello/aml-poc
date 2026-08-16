// Entry point: the only module that ties api.js, state.js, render.js and
// log.js together. Wires DOM events, orchestrates each action as
// api -> state -> render + log.

import * as api from "./api.js";
import * as state from "./state.js";
import * as render from "./render.js";
import * as log from "./log.js";

function errStatus(err) {
  return err.status ?? "ERR";
}

function errDetail(err) {
  return err.detail ?? err.message;
}

// Re-reads an alert from the backend and redraws both panes from it.
// Used after any failed action: the error response carries no alert
// object, so the only trustworthy way to "sync from the response" is a
// follow-up GET -- still backend-sourced, never UI-assumed.
async function resync(alertId) {
  try {
    const fresh = await api.getAlert(alertId);
    state.updateAlert(fresh);
    render.renderDetail(fresh);
    render.renderInbox(state.getAlerts(), state.getSelectedId());
  } catch (err) {
    log.logError(alertId, errStatus(err), errDetail(err));
  }
}

async function onRowClick(alertId) {
  render.renderDetailLoading(alertId);

  const current = state.getAlert(alertId);
  if (current && current.status === "pending") {
    try {
      const analyzed = await api.analyze(alertId);
      log.logTransition(alertId, "pending", analyzed.status);
      state.updateAlert(analyzed);
    } catch (err) {
      // A 409 here just means someone else already analyzed it since we
      // last looked -- not fatal, log it and keep going to the GET below,
      // which will render whatever the backend now reports.
      log.logError(alertId, errStatus(err), errDetail(err));
      if (err.status !== 409) return;
    }
  }

  let detail;
  try {
    detail = await api.getAlert(alertId);
  } catch (err) {
    log.logError(alertId, errStatus(err), errDetail(err));
    return;
  }

  state.updateAlert(detail);
  state.setSelected(alertId);
  render.renderDetail(detail);
  render.renderInbox(state.getAlerts(), state.getSelectedId());
}

async function onApprove(alertId) {
  const before = state.getAlert(alertId)?.status;
  let approved;
  try {
    approved = await api.approve(alertId);
  } catch (err) {
    log.logError(alertId, errStatus(err), errDetail(err));
    await resync(alertId);
    return;
  }
  state.updateAlert(approved);
  log.logTransition(alertId, before, approved.status);
  render.renderDetail(approved);
  render.renderInbox(state.getAlerts(), state.getSelectedId());

  // Approve drives execution -- the operator only ever sees one button,
  // but both transitions are real backend calls and both get logged.
  try {
    const executed = await api.execute(alertId);
    state.updateAlert(executed);
    log.logTransition(alertId, approved.status, executed.status);
    render.renderDetail(executed);
    render.renderInbox(state.getAlerts(), state.getSelectedId());
  } catch (err) {
    log.logError(alertId, errStatus(err), errDetail(err));
    await resync(alertId);
  }
}

async function onReject(alertId) {
  const before = state.getAlert(alertId)?.status;
  try {
    const rejected = await api.reject(alertId);
    state.updateAlert(rejected);
    log.logTransition(alertId, before, rejected.status);
    render.renderDetail(rejected);
    render.renderInbox(state.getAlerts(), state.getSelectedId());
  } catch (err) {
    log.logError(alertId, errStatus(err), errDetail(err));
    await resync(alertId);
  }
}

async function init() {
  log.init(document.getElementById("log-panel"));
  document.getElementById("log-clear-btn").addEventListener("click", () => log.clear());

  render.renderEmptyDetail();

  const alerts = await api.listAlerts();
  state.setAlerts(alerts);
  render.renderInbox(alerts, state.getSelectedId());

  document.getElementById("inbox-list").addEventListener("click", (e) => {
    const row = e.target.closest(".alert-row");
    if (row) onRowClick(row.dataset.id);
  });

  document.getElementById("detail-panel").addEventListener("click", (e) => {
    const approveBtn = e.target.closest(".approve-btn");
    const rejectBtn = e.target.closest(".reject-btn");
    if (approveBtn) onApprove(approveBtn.dataset.id);
    if (rejectBtn) onReject(rejectBtn.dataset.id);
  });
}

init();
