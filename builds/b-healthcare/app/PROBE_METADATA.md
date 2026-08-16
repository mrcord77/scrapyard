# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **4** · fully green: **4**.

### `/appointments` — PASS
- create: `POST /appointments` -> 201 (ok)
- read: `GET /appointments/1` -> 200 (ok)
- update: `PUT /appointments/1` -> 200 (ok)
- delete: `DELETE /appointments/1` -> 204 (ok)

### `/encounters` — PASS
- create: `POST /encounters` -> 201 (ok)
- read: `GET /encounters/1` -> 200 (ok)
- update: `PUT /encounters/1` -> 200 (ok)
- delete: `DELETE /encounters/1` -> 204 (ok)

### `/patients` — PASS
- create: `POST /patients` -> 201 (ok)
- read: `GET /patients/1` -> 200 (ok)
- update: `PUT /patients/1` -> 200 (ok)
- delete: `DELETE /patients/1` -> 204 (ok)

### `/providers` — PASS
- create: `POST /providers` -> 201 (ok)
- read: `GET /providers/1` -> 200 (ok)
- update: `PUT /providers/1` -> 200 (ok)
- delete: `DELETE /providers/1` -> 204 (ok)
