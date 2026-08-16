// Owns the transition-log panel DOM. Only appends formatted, timestamped
// lines -- it never fetches and never decides what happened, it only
// records what main.js tells it the backend reported.

let container = null;

export function init(containerEl) {
  container = containerEl;
}

function timestamp() {
  return new Date().toTimeString().slice(0, 8); // HH:MM:SS
}

function appendLine(text, cls) {
  const line = document.createElement("div");
  line.className = `log-line ${cls}`;
  line.textContent = `${timestamp()}  ${text}`;
  container.appendChild(line);
  container.scrollTop = container.scrollHeight;
}

// Logs a transition exactly as the backend's response reported it --
// callers pass the from/to status strings they read off an API response,
// never a status the UI assumed on its own.
export function logTransition(alertId, fromStatus, toStatus) {
  appendLine(`${alertId}  ${fromStatus} → ${toStatus}`, "log-ok");
}

export function logError(alertId, status, detail) {
  const label =
    status === 404 ? "404 Not Found" : status === 409 ? "409 Conflict" : `${status} Error`;
  appendLine(`${alertId}  ${label}: ${detail}`, "log-err");
}

export function clear() {
  container.innerHTML = "";
}
