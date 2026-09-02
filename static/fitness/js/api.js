// fetch() wrappers for the backend query API (see fitness/API-CONTRACT.md).
// Same-origin paths under /fitness/api - served by the main app's
// backend/server.py, which mounts backend/fitness/api.py's handlers there.

function handleUnauthorized(body) {
  const target = (body && body.reauth_url) || "/fitness/login?error=session_expired";
  window.location.assign(target);
  // Never resolves: the navigation is already committed, and resolving
  // would let the caller render an error flash over a page that is leaving.
  return new Promise(() => {});
}

async function getJSON(path) {
  const res = await fetch(path);
  const body = await res.json().catch(() => null);
  if (res.status === 401) {
    return handleUnauthorized(body);
  }
  if (!res.ok) {
    throw new Error((body && body.error) || `${res.status} ${res.statusText}`);
  }
  return body;
}

function rangeQuery(from, to) {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function getHealth() {
  return getJSON("/fitness/api/health");
}

export function getMetrics(from, to) {
  return getJSON(`/fitness/api/metrics${rangeQuery(from, to)}`);
}

export function getMetricDetail(metric, from, to) {
  return getJSON(`/fitness/api/metrics/${encodeURIComponent(metric)}${rangeQuery(from, to)}`);
}

// `from`/`to` here are full ISO 8601 UTC instants (e.g. an activity's own
// start_time/end_time), not the bare dates rangeQuery() builds elsewhere -
// see fitness/API-CONTRACT.md's GET /fitness/api/metrics/{metric}/samples.
export function getMetricSamples(metric, fromInstant, toInstant) {
  const params = new URLSearchParams({ from: fromInstant, to: toInstant });
  return getJSON(`/fitness/api/metrics/${encodeURIComponent(metric)}/samples?${params.toString()}`);
}

export async function triggerSync() {
  const res = await fetch("/fitness/api/sync", { method: "POST" });
  const body = await res.json().catch(() => null);
  if (res.status === 401) {
    return handleUnauthorized(body);
  }
  if (!res.ok) {
    throw new Error((body && body.error) || `${res.status} ${res.statusText}`);
  }
  return body;
}

export function getMe() {
  return getJSON("/fitness/api/me");
}

export async function signOut() {
  await fetch("/fitness/auth/logout", { method: "POST" });
  window.location.assign("/fitness/login");
}
