# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **5** · fully green: **5**.

### `/experiments` — PASS
- create: `POST /experiments` -> 201 (ok)
- read: `GET /experiments/1` -> 200 (ok)
- update: `PUT /experiments/1` -> 200 (ok)
- transition_guard: `POST /experiments/1/transition` -> 409 (ok)
- delete: `DELETE /experiments/1` -> 204 (ok)

### `/notes` — PASS
- create: `POST /notes` -> 201 (ok)
- read: `GET /notes/1` -> 200 (ok)
- update: `PUT /notes/1` -> 200 (ok)
- delete: `DELETE /notes/1` -> 204 (ok)

### `/research_docs` — PASS
- create: `POST /research_docs` -> 201 (ok)
- read: `GET /research_docs/1` -> 200 (ok)
- update: `PUT /research_docs/1` -> 200 (ok)
- transition_guard: `POST /research_docs/1/transition` -> 409 (ok)
- delete: `DELETE /research_docs/1` -> 204 (ok)

### `/runs` — PASS
- create: `POST /runs` -> 201 (ok)
- read: `GET /runs/1` -> 200 (ok)
- update: `PUT /runs/1` -> 200 (ok)
- transition_guard: `POST /runs/1/transition` -> 409 (ok)
- delete: `DELETE /runs/1` -> 204 (ok)

### `/tags` — PASS
- create: `POST /tags` -> 201 (ok)
- read: `GET /tags/1` -> 200 (ok)
- update: `PUT /tags/1` -> 200 (ok)
- delete: `DELETE /tags/1` -> 204 (ok)
