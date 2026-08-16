"""
gen_frontend_react.py — Write a real Vite + React frontend over the proven API.

This is the L1 upgrade from the server-rendered vanilla-JS SPA: an actual Vite/React
project (JSX components, a fetch API client, a dev proxy to the backend) that builds
to static assets with `npm run build`. The build itself is the proof.
"""
from __future__ import annotations
import os
import json

_PKG = {
    "name": "scrapyard-frontend",
    "private": True,
    "version": "0.1.0",
    "type": "module",
    "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
    "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
    "devDependencies": {"@vitejs/plugin-react": "^4.3.4", "vite": "^5.4.11"},
}

_VITE_CONFIG = """import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// /api is proxied to the FastAPI backend in dev; in prod set VITE_API_URL.
export default defineConfig({
  // relative base: built assets resolve correctly wherever the SPA is mounted
  // (eos serves it under /app/, not the domain root)
  base: './',
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\\/api/, ''),
      },
    },
  },
})
"""

_INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Scrapyard App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""

_MAIN_JSX = """import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
"""

_API_JS = """// Typed-ish fetch client targeting the proven FastAPI routes.
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
"""

_APP_JSX = """import React, { useEffect, useState } from 'react'
import { api } from './api.js'

function StatusBar() {
  const [health, setHealth] = useState(null)
  const [caps, setCaps] = useState(null)
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ ok: false }))
    api.capabilities().then(setCaps).catch(() => setCaps(null))
  }, [])
  return (
    <div className="status">
      <span className={health?.ok ? 'dot ok' : 'dot bad'} />
      <span>{health?.ok ? 'API healthy' : 'API unreachable'}</span>
      {caps && <span className="muted"> — {caps.feature_routes_count} feature route(s)</span>}
    </div>
  )
}

function LoginForm({ onAuthed }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      const out = await api.login(email, password)
      onAuthed(out)
    } catch (err) {
      setError('Login failed — check your credentials.')
    }
  }
  return (
    <form className="card" onSubmit={submit}>
      <h2>Sign in</h2>
      <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" type="email" />
      <input value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" type="password" />
      <button type="submit">Sign in</button>
      {error && <p className="error">{error}</p>}
    </form>
  )
}

export default function App() {
  const [session, setSession] = useState(null)
  return (
    <main className="app">
      <header>
        <h1>Scrapyard App</h1>
        <StatusBar />
      </header>
      {session ? (
        <section className="card">
          <h2>Welcome</h2>
          <p>You are signed in.</p>
          <button onClick={() => setSession(null)}>Sign out</button>
        </section>
      ) : (
        <LoginForm onAuthed={setSession} />
      )}
    </main>
  )
}
"""

_STYLES = """:root { font-family: system-ui, sans-serif; color: #1a1a1a; }
.app { max-width: 560px; margin: 3rem auto; padding: 0 1rem; }
header { display: flex; justify-content: space-between; align-items: center; }
.status { display: flex; gap: .4rem; align-items: center; font-size: .9rem; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.dot.ok { background: #16a34a; } .dot.bad { background: #dc2626; }
.muted { color: #6b7280; }
.card { border: 1px solid #e5e7eb; border-radius: 12px; padding: 1.5rem; margin-top: 1.5rem; display: flex; flex-direction: column; gap: .75rem; }
input { padding: .6rem; border: 1px solid #d1d5db; border-radius: 8px; font-size: 1rem; }
button { padding: .6rem 1rem; border: 0; border-radius: 8px; background: #111827; color: white; font-size: 1rem; cursor: pointer; }
.error { color: #dc2626; font-size: .9rem; }
"""


def write_react_frontend(out_dir: str) -> dict:
    fe = os.path.join(out_dir, "frontend")
    os.makedirs(os.path.join(fe, "src"), exist_ok=True)
    files = {
        "package.json": json.dumps(_PKG, indent=2) + "\n",
        "vite.config.js": _VITE_CONFIG,
        "index.html": _INDEX_HTML,
        ".gitignore": "node_modules\ndist\n",
        "src/main.jsx": _MAIN_JSX,
        "src/api.js": _API_JS,
        "src/App.jsx": _APP_JSX,
        "src/styles.css": _STYLES,
    }
    for rel, content in files.items():
        path = os.path.join(fe, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    return {"written": [f"frontend/{r}" for r in files]}
