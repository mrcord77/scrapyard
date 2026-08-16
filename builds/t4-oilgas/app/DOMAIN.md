# Domain: Upstream/field operations

## Terminology
- **well** — a drilling/production site
- **lease** — land/mineral rights
- **run ticket** — volume transfer record
- **downtime** — non-producing period

## Entities to scaffold
- **Well**: id, name, lease_id, status, location
- **Lease**: id, name, operator, county, state
- **ProductionLog**: id, well_id, date, oil_bbl, gas_mcf, water_bbl
- **WorkOrder**: id, well_id, kind, status, scheduled_at

## Workflows
- log daily production
- schedule + close work orders
- downtime tracking
- lease/well rollup reporting

## Permissions
- well.manage
- production.log
- workorder.assign

## Reports
- production by well/lease
- downtime hours
- work order backlog
