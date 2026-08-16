# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **4** · fully green: **4**.

### `/accounts` — PASS
- create: `POST /accounts` -> 201 (ok)
- read: `GET /accounts/1` -> 200 (ok)
- update: `PUT /accounts/1` -> 200 (ok)
- delete: `DELETE /accounts/1` -> 204 (ok)

### `/invitations` — PASS
- create: `POST /invitations` -> 201 (ok)
- read: `GET /invitations/1` -> 200 (ok)
- update: `PUT /invitations/1` -> 200 (ok)
- delete: `DELETE /invitations/1` -> 204 (ok)

### `/members` — PASS
- create: `POST /members` -> 201 (ok)
- read: `GET /members/1` -> 200 (ok)
- update: `PUT /members/1` -> 200 (ok)
- delete: `DELETE /members/1` -> 204 (ok)

### `/plans` — PASS
- create: `POST /plans` -> 201 (ok)
- read: `GET /plans/1` -> 200 (ok)
- update: `PUT /plans/1` -> 200 (ok)
- delete: `DELETE /plans/1` -> 204 (ok)
