// Thin fetch wrapper around the FastAPI endpoints. No DOM access here --
// callers (main.js) decide what to do with the data or the error.

const BASE = "/api/alerts";

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `Request failed with status ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, options) {
  const res = await fetch(path, options);
  let body = null;
  try {
    body = await res.json();
  } catch {
    // No JSON body (e.g. a non-FastAPI error) -- fall through with body=null.
  }
  if (!res.ok) {
    const detail = body && body.detail ? body.detail : res.statusText;
    throw new ApiError(res.status, detail);
  }
  return body;
}

export function listAlerts() {
  return request(BASE);
}

export function getAlert(id) {
  return request(`${BASE}/${encodeURIComponent(id)}`);
}

export function analyze(id) {
  return request(`${BASE}/${encodeURIComponent(id)}/analyze`, { method: "POST" });
}

export function approve(id) {
  return request(`${BASE}/${encodeURIComponent(id)}/approve`, { method: "POST" });
}

export function reject(id) {
  return request(`${BASE}/${encodeURIComponent(id)}/reject`, { method: "POST" });
}

export function execute(id) {
  return request(`${BASE}/${encodeURIComponent(id)}/execute`, { method: "POST" });
}
