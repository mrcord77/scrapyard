import React, { useEffect, useState } from 'react'
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
