# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **1** · fully green: **1**.

### `/leads` — PASS
- create: `POST /leads` -> 201 (ok)
- read: `GET /leads/1` -> 200 (ok)
- update: `PUT /leads/1` -> 200 (ok)
- delete: `DELETE /leads/1` -> 204 (ok)
