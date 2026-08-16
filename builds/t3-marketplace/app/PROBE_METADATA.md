# Probe metadata

_Per-entity record of what the runtime verifier exercised over HTTP._

Auth: **session**.

Entities probed: **5** · fully green: **5**.

### `/carts` — PASS
- create: `POST /carts` -> 201 (ok)
- read: `GET /carts/1` -> 200 (ok)
- update: `PUT /carts/1` -> 200 (ok)
- delete: `DELETE /carts/1` -> 204 (ok)

### `/orders` — PASS
- create: `POST /orders` -> 201 (ok)
- read: `GET /orders/1` -> 200 (ok)
- update: `PUT /orders/1` -> 200 (ok)
- delete: `DELETE /orders/1` -> 204 (ok)

### `/products` — PASS
- create: `POST /products` -> 201 (ok)
- read: `GET /products/1` -> 200 (ok)
- update: `PUT /products/1` -> 200 (ok)
- delete: `DELETE /products/1` -> 204 (ok)

### `/shipments` — PASS
- create: `POST /shipments` -> 201 (ok)
- read: `GET /shipments/1` -> 200 (ok)
- update: `PUT /shipments/1` -> 200 (ok)
- delete: `DELETE /shipments/1` -> 204 (ok)

### `/variants` — PASS
- create: `POST /variants` -> 201 (ok)
- read: `GET /variants/1` -> 200 (ok)
- update: `PUT /variants/1` -> 200 (ok)
- delete: `DELETE /variants/1` -> 204 (ok)
