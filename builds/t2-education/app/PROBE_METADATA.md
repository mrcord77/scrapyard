# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **5** · fully green: **5**.

### `/courses` — PASS
- create: `POST /courses` -> 201 (ok)
- read: `GET /courses/1` -> 200 (ok)
- update: `PUT /courses/1` -> 200 (ok)
- delete: `DELETE /courses/1` -> 204 (ok)

### `/enrollments` — PASS
- create: `POST /enrollments` -> 201 (ok)
- read: `GET /enrollments/1` -> 200 (ok)
- update: `PUT /enrollments/1` -> 200 (ok)
- delete: `DELETE /enrollments/1` -> 204 (ok)

### `/lessons` — PASS
- create: `POST /lessons` -> 201 (ok)
- read: `GET /lessons/1` -> 200 (ok)
- update: `PUT /lessons/1` -> 200 (ok)
- delete: `DELETE /lessons/1` -> 204 (ok)

### `/modules` — PASS
- create: `POST /modules` -> 201 (ok)
- read: `GET /modules/1` -> 200 (ok)
- update: `PUT /modules/1` -> 200 (ok)
- delete: `DELETE /modules/1` -> 204 (ok)

### `/progresses` — PASS
- create: `POST /progresses` -> 201 (ok)
- read: `GET /progresses/1` -> 200 (ok)
- update: `PUT /progresses/1` -> 200 (ok)
- delete: `DELETE /progresses/1` -> 204 (ok)
