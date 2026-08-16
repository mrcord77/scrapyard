# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **3** · fully green: **3**.

### `/memberships` — PASS
- create: `POST /memberships` -> 201 (ok)
- read: `GET /memberships/1` -> 200 (ok)
- update: `PUT /memberships/1` -> 200 (ok)
- delete: `DELETE /memberships/1` -> 204 (ok)

### `/posts` — PASS
- create: `POST /posts` -> 201 (ok)
- read: `GET /posts/1` -> 200 (ok)
- update: `PUT /posts/1` -> 200 (ok)
- delete: `DELETE /posts/1` -> 204 (ok)

### `/users` — PASS
- create: `POST /users` -> 201 (ok)
- read: `GET /users/1` -> 200 (ok)
- update: `PUT /users/1` -> 200 (ok)
- delete: `DELETE /users/1` -> 204 (ok)
