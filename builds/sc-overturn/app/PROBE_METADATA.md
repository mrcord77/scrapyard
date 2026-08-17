# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **5** · fully green: **5**.

### `/appeals` — PASS
- create: `POST /appeals` -> 201 (ok)
- read: `GET /appeals/1` -> 200 (ok)
- update: `PUT /appeals/1` -> 200 (ok)
- transition_guard: `POST /appeals/1/transition` -> 409 (ok)
- delete: `DELETE /appeals/1` -> 204 (ok)

### `/call_logs` — PASS
- create: `POST /call_logs` -> 201 (ok)
- read: `GET /call_logs/1` -> 200 (ok)
- update: `PUT /call_logs/1` -> 200 (ok)
- delete: `DELETE /call_logs/1` -> 204 (ok)

### `/claims` — PASS
- create: `POST /claims` -> 201 (ok)
- read: `GET /claims/1` -> 200 (ok)
- update: `PUT /claims/1` -> 200 (ok)
- transition_guard: `POST /claims/1/transition` -> 409 (ok)
- delete: `DELETE /claims/1` -> 204 (ok)

### `/denials` — PASS
- create: `POST /denials` -> 201 (ok)
- read: `GET /denials/1` -> 200 (ok)
- update: `PUT /denials/1` -> 200 (ok)
- delete: `DELETE /denials/1` -> 204 (ok)

### `/evidence_items` — PASS
- create: `POST /evidence_items` -> 201 (ok)
- read: `GET /evidence_items/1` -> 200 (ok)
- update: `PUT /evidence_items/1` -> 200 (ok)
- delete: `DELETE /evidence_items/1` -> 204 (ok)
