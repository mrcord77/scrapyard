// Typed-ish fetch client targeting the proven FastAPI routes.
const BASE = import.meta.env.VITE_API_URL || '/api'

async function jsonOrThrow(res) {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const api = {
  health: () => fetch(`${BASE}/health`).then(jsonOrThrow),
  capabilities: () => fetch(`${BASE}/capabilities`).then(jsonOrThrow),
  ready: () => fetch(`${BASE}/readyz`).then((r) => ({ ok: r.ok, status: r.status })),
  login: (email, password) =>
    fetch(`${BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    }).then(jsonOrThrow),
  register: (email, password) =>
    fetch(`${BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    }).then(jsonOrThrow),
}
