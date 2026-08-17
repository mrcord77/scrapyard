# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **6** · fully green: **6**.

### `/appointments` — PASS
- create: `POST /appointments` -> 201 (ok)
- read: `GET /appointments/1` -> 200 (ok)
- update: `PUT /appointments/1` -> 200 (ok)
- transition_guard: `POST /appointments/1/transition` -> 409 (ok)
- delete: `DELETE /appointments/1` -> 204 (ok)

### `/care_recipients` — PASS
- create: `POST /care_recipients` -> 201 (ok)
- read: `GET /care_recipients/1` -> 200 (ok)
- update: `PUT /care_recipients/1` -> 200 (ok)
- delete: `DELETE /care_recipients/1` -> 204 (ok)

### `/care_tasks` — PASS
- create: `POST /care_tasks` -> 201 (ok)
- read: `GET /care_tasks/1` -> 200 (ok)
- update: `PUT /care_tasks/1` -> 200 (ok)
- transition_guard: `POST /care_tasks/1/transition` -> 409 (ok)
- delete: `DELETE /care_tasks/1` -> 204 (ok)

### `/dose_logs` — PASS
- create: `POST /dose_logs` -> 201 (ok)
- read: `GET /dose_logs/1` -> 200 (ok)
- update: `PUT /dose_logs/1` -> 200 (ok)
- delete: `DELETE /dose_logs/1` -> 204 (ok)

### `/medications` — PASS
- create: `POST /medications` -> 201 (ok)
- read: `GET /medications/1` -> 200 (ok)
- update: `PUT /medications/1` -> 200 (ok)
- transition_guard: `POST /medications/1/transition` -> 409 (ok)
- delete: `DELETE /medications/1` -> 204 (ok)

### `/updates` — PASS
- create: `POST /updates` -> 201 (ok)
- read: `GET /updates/1` -> 200 (ok)
- update: `PUT /updates/1` -> 200 (ok)
- delete: `DELETE /updates/1` -> 204 (ok)
