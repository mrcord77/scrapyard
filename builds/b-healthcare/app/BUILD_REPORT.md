# Build report — Health / clinical (NON-clinical-decision; admin & scheduling focus)

Domain `healthcare` · data sensitivity **high**.

_Generated from the resolved domain; describes what the code generators actually emitted._

## Summary

- Entities: **4**
- Relationships with enforced foreign keys: **3**
- Workflows (state machines): **0**
- Many-to-many links: **0**
- Entities requiring auth: **4**
- Entities owner-scoped: **2**
- Entities with encrypted fields: **2**

## Entities

### Patient  (`patients`)
- Security: auth, owner=user_id, encrypted=mrn, audit=create,update,delete
- Indexed (owner/external, no FK): `user_id`
- Workflow: no

### Provider  (`providers`)
- Security: auth, owner=user_id, audit=create,update,delete
- Indexed (owner/external, no FK): `user_id`
- Workflow: no

### Appointment  (`appointments`)
- Security: auth
- Foreign keys: `patient_id` → `patients`; `provider_id` → `providers`
- Workflow: no

### Encounter  (`encounters`)
- Security: auth, encrypted=notes_ref
- Foreign keys: `appointment_id` → `appointments`
- Workflow: no

## Enforced by generation

- Per-entity tables with primary keys and Alembic-compatible models.
- Client-supplied <entity>_id columns are real FOREIGN KEYs (+ index); orphaned references are rejected (409).
- Server-set owner columns (user_id) are indexed; ownership is forced from the authenticated principal.
- Declared state machines: only listed transitions are allowed; target-state guards must hold; violations return 409.
- Auth / owner-scoping / field encryption / audit per the entity's data-sensitivity policy.

## NOT enforced (by design, this build)

- many-to-many is now generated from a domain many_to_many declaration (join table with two CASCADE FKs + a uniqueness constraint, plus a link service and attach/detach/list routes) — proven by the many_to_many contract + HTTP e2e; still pending: relationships are otherwise inferred from <entity>_id naming (one-to-many / many-to-one), and richer declared relationship metadata (named roles, through-attributes on the join row) is not generated
- still pending: guards now support same-row (field==value) AND cross-entity (related row status) checks; what remains is SIDE EFFECTS on transition (e.g. a damaged return auto-creating an incident + maintenance record and locking the tool), time-based transitions, and notifications
