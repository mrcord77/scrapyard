# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **3** · fully green: **3**.

### `/labels` — PASS
- create: `POST /labels` -> 201 (ok)
- read: `GET /labels/1` -> 200 (ok)
- update: `PUT /labels/1` -> 200 (ok)
- delete: `DELETE /labels/1` -> 204 (ok)

### `/projects` — PASS
- create: `POST /projects` -> 201 (ok)
- read: `GET /projects/1` -> 200 (ok)
- update: `PUT /projects/1` -> 200 (ok)
- transition_guard: `POST /projects/1/transition` -> 409 (ok)
- delete: `DELETE /projects/1` -> 204 (ok)

### `/tasks` — PASS
- create: `POST /tasks` -> 201 (ok)
- read: `GET /tasks/1` -> 200 (ok)
- update: `PUT /tasks/1` -> 200 (ok)
- transition_guard: `POST /tasks/1/transition` -> 409 (ok)
- delete: `DELETE /tasks/1` -> 204 (ok)
