# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session+admin**.

Entities probed: **2** · fully green: **2**.

### `/repair_tickets` — PASS
- create: `POST /repair_tickets` -> 201 (ok)
- read: `GET /repair_tickets/1` -> 200 (ok)
- update: `PUT /repair_tickets/1` -> 200 (ok)
- transition_guard: `POST /repair_tickets/1/transition` -> 409 (ok)
- delete: `DELETE /repair_tickets/1` -> 204 (ok)

### `/users` — PASS
- create: `POST /users` -> 201 (ok)
- read: `GET /users/1` -> 200 (ok)
- update: `PUT /users/1` -> 200 (ok)
- delete: `DELETE /users/1` -> 204 (ok)
