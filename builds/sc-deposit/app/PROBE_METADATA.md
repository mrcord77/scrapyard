# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **4** · fully green: **4**.

### `/deductions` — PASS
- create: `POST /deductions` -> 201 (ok)
- read: `GET /deductions/1` -> 200 (ok)
- update: `PUT /deductions/1` -> 200 (ok)
- transition_guard: `POST /deductions/1/transition` -> 409 (ok)
- delete: `DELETE /deductions/1` -> 204 (ok)

### `/dispute_letters` — PASS
- create: `POST /dispute_letters` -> 201 (ok)
- read: `GET /dispute_letters/1` -> 200 (ok)
- update: `PUT /dispute_letters/1` -> 200 (ok)
- delete: `DELETE /dispute_letters/1` -> 204 (ok)

### `/evidence_shots` — PASS
- create: `POST /evidence_shots` -> 201 (ok)
- read: `GET /evidence_shots/1` -> 200 (ok)
- update: `PUT /evidence_shots/1` -> 200 (ok)
- delete: `DELETE /evidence_shots/1` -> 204 (ok)

### `/tenancies` — PASS
- create: `POST /tenancies` -> 201 (ok)
- read: `GET /tenancies/1` -> 200 (ok)
- update: `PUT /tenancies/1` -> 200 (ok)
- transition_guard: `POST /tenancies/1/transition` -> 409 (ok)
- delete: `DELETE /tenancies/1` -> 204 (ok)
