# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **9** · fully green: **9**.

### `/attendances` — PASS
- create: `POST /attendances` -> 201 (ok)
- read: `GET /attendances/1` -> 200 (ok)
- update: `PUT /attendances/1` -> 200 (ok)
- delete: `DELETE /attendances/1` -> 204 (ok)

### `/chips` — PASS
- create: `POST /chips` -> 201 (ok)
- read: `GET /chips/1` -> 200 (ok)
- update: `PUT /chips/1` -> 200 (ok)
- delete: `DELETE /chips/1` -> 204 (ok)

### `/journal_entries` — PASS
- create: `POST /journal_entries` -> 201 (ok)
- read: `GET /journal_entries/1` -> 200 (ok)
- update: `PUT /journal_entries/1` -> 200 (ok)
- delete: `DELETE /journal_entries/1` -> 204 (ok)

### `/meetings` — PASS
- create: `POST /meetings` -> 201 (ok)
- read: `GET /meetings/1` -> 200 (ok)
- update: `PUT /meetings/1` -> 200 (ok)
- delete: `DELETE /meetings/1` -> 204 (ok)

### `/memberships` — PASS
- create: `POST /memberships` -> 201 (ok)
- read: `GET /memberships/1` -> 200 (ok)
- update: `PUT /memberships/1` -> 200 (ok)
- delete: `DELETE /memberships/1` -> 204 (ok)

### `/milestones` — PASS
- create: `POST /milestones` -> 201 (ok)
- read: `GET /milestones/1` -> 200 (ok)
- update: `PUT /milestones/1` -> 200 (ok)
- delete: `DELETE /milestones/1` -> 204 (ok)

### `/posts` — PASS
- create: `POST /posts` -> 201 (ok)
- read: `GET /posts/1` -> 200 (ok)
- update: `PUT /posts/1` -> 200 (ok)
- delete: `DELETE /posts/1` -> 204 (ok)

### `/sponsors` — PASS
- create: `POST /sponsors` -> 201 (ok)
- read: `GET /sponsors/1` -> 200 (ok)
- update: `PUT /sponsors/1` -> 200 (ok)
- delete: `DELETE /sponsors/1` -> 204 (ok)

### `/users` — PASS
- create: `POST /users` -> 201 (ok)
- read: `GET /users/1` -> 200 (ok)
- update: `PUT /users/1` -> 200 (ok)
- delete: `DELETE /users/1` -> 204 (ok)
