# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **4** · fully green: **4**.

### `/leases` — PASS
- create: `POST /leases` -> 201 (ok)
- read: `GET /leases/1` -> 200 (ok)
- update: `PUT /leases/1` -> 200 (ok)
- delete: `DELETE /leases/1` -> 204 (ok)

### `/production_logs` — PASS
- create: `POST /production_logs` -> 201 (ok)
- read: `GET /production_logs/1` -> 200 (ok)
- update: `PUT /production_logs/1` -> 200 (ok)
- delete: `DELETE /production_logs/1` -> 204 (ok)

### `/wells` — PASS
- create: `POST /wells` -> 201 (ok)
- read: `GET /wells/1` -> 200 (ok)
- update: `PUT /wells/1` -> 200 (ok)
- delete: `DELETE /wells/1` -> 204 (ok)

### `/work_orders` — PASS
- create: `POST /work_orders` -> 201 (ok)
- read: `GET /work_orders/1` -> 200 (ok)
- update: `PUT /work_orders/1` -> 200 (ok)
- delete: `DELETE /work_orders/1` -> 204 (ok)
