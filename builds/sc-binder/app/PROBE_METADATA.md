# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **5** · fully green: **5**.

### `/action_items` — PASS
- create: `POST /action_items` -> 201 (ok)
- read: `GET /action_items/1` -> 200 (ok)
- update: `PUT /action_items/1` -> 200 (ok)
- transition_guard: `POST /action_items/1/transition` -> 409 (ok)
- delete: `DELETE /action_items/1` -> 204 (ok)

### `/children` — PASS
- create: `POST /children` -> 201 (ok)
- read: `GET /children/1` -> 200 (ok)
- update: `PUT /children/1` -> 200 (ok)
- delete: `DELETE /children/1` -> 204 (ok)

### `/correspondences` — PASS
- create: `POST /correspondences` -> 201 (ok)
- read: `GET /correspondences/1` -> 200 (ok)
- update: `PUT /correspondences/1` -> 200 (ok)
- delete: `DELETE /correspondences/1` -> 204 (ok)

### `/meetings` — PASS
- create: `POST /meetings` -> 201 (ok)
- read: `GET /meetings/1` -> 200 (ok)
- update: `PUT /meetings/1` -> 200 (ok)
- transition_guard: `POST /meetings/1/transition` -> 409 (ok)
- delete: `DELETE /meetings/1` -> 204 (ok)

### `/service_entries` — PASS
- create: `POST /service_entries` -> 201 (ok)
- read: `GET /service_entries/1` -> 200 (ok)
- update: `PUT /service_entries/1` -> 200 (ok)
- delete: `DELETE /service_entries/1` -> 204 (ok)
