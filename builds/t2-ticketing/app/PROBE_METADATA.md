# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **4** · fully green: **4**.

### `/change_orders` — PASS
- create: `POST /change_orders` -> 201 (ok)
- read: `GET /change_orders/1` -> 200 (ok)
- update: `PUT /change_orders/1` -> 200 (ok)
- delete: `DELETE /change_orders/1` -> 204 (ok)

### `/documents` — PASS
- create: `POST /documents` -> 201 (ok)
- read: `GET /documents/1` -> 200 (ok)
- update: `PUT /documents/1` -> 200 (ok)
- delete: `DELETE /documents/1` -> 204 (ok)

### `/projects` — PASS
- create: `POST /projects` -> 201 (ok)
- read: `GET /projects/1` -> 200 (ok)
- update: `PUT /projects/1` -> 200 (ok)
- delete: `DELETE /projects/1` -> 204 (ok)

### `/tasks` — PASS
- create: `POST /tasks` -> 201 (ok)
- read: `GET /tasks/1` -> 200 (ok)
- update: `PUT /tasks/1` -> 200 (ok)
- delete: `DELETE /tasks/1` -> 204 (ok)
