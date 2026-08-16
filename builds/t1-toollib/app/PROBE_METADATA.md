# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **6** · fully green: **6**.

### `/incidents` — PASS
- create: `POST /incidents` -> 201 (ok)
- read: `GET /incidents/1` -> 200 (ok)
- update: `PUT /incidents/1` -> 200 (ok)
- delete: `DELETE /incidents/1` -> 204 (ok)

### `/maintenance_records` — PASS
- create: `POST /maintenance_records` -> 201 (ok)
- read: `GET /maintenance_records/1` -> 200 (ok)
- update: `PUT /maintenance_records/1` -> 200 (ok)
- transition_guard: `POST /maintenance_records/1/transition` -> 409 (ok)
- delete: `DELETE /maintenance_records/1` -> 204 (ok)

### `/members` — PASS
- create: `POST /members` -> 201 (ok)
- read: `GET /members/1` -> 200 (ok)
- update: `PUT /members/1` -> 200 (ok)
- transition_guard: `POST /members/1/transition` -> 409 (ok)
- delete: `DELETE /members/1` -> 204 (ok)

### `/reservations` — PASS
- create: `POST /reservations` -> 201 (ok)
- read: `GET /reservations/1` -> 200 (ok)
- update: `PUT /reservations/1` -> 200 (ok)
- transition_guard: `POST /reservations/1/transition` -> 409 (ok)
- delete: `DELETE /reservations/1` -> 204 (ok)

### `/tags` — PASS
- create: `POST /tags` -> 201 (ok)
- read: `GET /tags/1` -> 200 (ok)
- update: `PUT /tags/1` -> 200 (ok)
- delete: `DELETE /tags/1` -> 204 (ok)

### `/tools` — PASS
- create: `POST /tools` -> 201 (ok)
- read: `GET /tools/1` -> 200 (ok)
- update: `PUT /tools/1` -> 200 (ok)
- transition_guard: `POST /tools/1/transition` -> 409 (ok)
- delete: `DELETE /tools/1` -> 204 (ok)
