# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **4** · fully green: **4**.

### `/agents` — PASS
- create: `POST /agents` -> 201 (ok)
- read: `GET /agents/1` -> 200 (ok)
- update: `PUT /agents/1` -> 200 (ok)
- delete: `DELETE /agents/1` -> 204 (ok)

### `/inquiries` — PASS
- create: `POST /inquiries` -> 201 (ok)
- read: `GET /inquiries/1` -> 200 (ok)
- update: `PUT /inquiries/1` -> 200 (ok)
- delete: `DELETE /inquiries/1` -> 204 (ok)

### `/listings` — PASS
- create: `POST /listings` -> 201 (ok)
- read: `GET /listings/1` -> 200 (ok)
- update: `PUT /listings/1` -> 200 (ok)
- delete: `DELETE /listings/1` -> 204 (ok)

### `/showings` — PASS
- create: `POST /showings` -> 201 (ok)
- read: `GET /showings/1` -> 200 (ok)
- update: `PUT /showings/1` -> 200 (ok)
- delete: `DELETE /showings/1` -> 204 (ok)
