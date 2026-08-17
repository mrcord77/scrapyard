# Build report — The Binder

Domain `iep_binder` · data sensitivity **high**.

_Generated from the resolved domain; describes what the code generators actually emitted._

## Summary

- Entities: **5**
- Relationships with enforced foreign keys: **4**
- Workflows (state machines): **2**
- Many-to-many links: **0**
- Entities requiring auth: **5**
- Entities owner-scoped: **5**
- Entities with encrypted fields: **3**

## Entities

### Child  (`children`)
- Security: auth, owner=user_id, encrypted=first_name,diagnosis,notes, audit=create,update,delete
- Indexed (owner/external, no FK): `user_id`
- Workflow: no

### Meeting  (`meetings`)
- Security: auth, owner=user_id, encrypted=notes,attendees, audit=create,update
- Foreign keys: `child_id` → `children`
- Indexed (owner/external, no FK): `user_id`
- Workflow: yes
- Reference rule: `child_id` must reference an existing `Child`

### Correspondence  (`correspondences`)
- Security: auth, owner=user_id, encrypted=body,subject, audit=create
- Foreign keys: `child_id` → `children`
- Indexed (owner/external, no FK): `user_id`
- Workflow: no

### ServiceEntry  (`service_entries`)
- Security: auth, owner=user_id, audit=create,update,delete
- Foreign keys: `child_id` → `children`
- Indexed (owner/external, no FK): `user_id`
- Workflow: no

### ActionItem  (`action_items`)
- Security: auth, owner=user_id, audit=create,update,delete
- Foreign keys: `child_id` → `children`
- Indexed (owner/external, no FK): `user_id`
- Workflow: yes

## Workflows

### Meeting.status (initial: `requested`)
- `requested` → `scheduled`, `refused`
- `scheduled` → `held`, `cancelled_by_school`, `rescheduled`
- `rescheduled` → `scheduled`
- `held` → `minutes_received`, `disputed`
- `minutes_received` → 
- `disputed` → `resolved`, `state_complaint`
- `refused` → `state_complaint`
- `cancelled_by_school` → `rescheduled`, `state_complaint`
- `state_complaint` → `resolved`
- `resolved` → 

### ActionItem.status (initial: `open`)
- `open` → `done`, `overdue`, `dropped`
- `overdue` → `done`, `escalated`
- `escalated` → `done`
- `done` → 
- `dropped` → 

## Enforced by generation

- Per-entity tables with primary keys and Alembic-compatible models.
- Client-supplied <entity>_id columns are real FOREIGN KEYs (+ index); orphaned references are rejected (409).
- Server-set owner columns (user_id) are indexed; ownership is forced from the authenticated principal.
- Declared state machines: only listed transitions are allowed; target-state guards must hold; violations return 409.
- Auth / owner-scoping / field encryption / audit per the entity's data-sensitivity policy.

## NOT enforced (by design, this build)

- many-to-many is now generated from a domain many_to_many declaration (join table with two CASCADE FKs + a uniqueness constraint, plus a link service and attach/detach/list routes) — proven by the many_to_many contract + HTTP e2e; still pending: relationships are otherwise inferred from <entity>_id naming (one-to-many / many-to-one), and richer declared relationship metadata (named roles, through-attributes on the join row) is not generated
- still pending: guards now support same-row (field==value) AND cross-entity (related row status) checks; what remains is SIDE EFFECTS on transition (e.g. a damaged return auto-creating an incident + maintenance record and locking the tool), time-based transitions, and notifications
