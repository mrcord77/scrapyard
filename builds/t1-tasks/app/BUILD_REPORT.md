# Build report — Personal Task Tracker

Domain `task_tracker` · data sensitivity **moderate**.

_Generated from the resolved domain; describes what the code generators actually emitted._

## Summary

- Entities: **3**
- Relationships with enforced foreign keys: **1**
- Workflows (state machines): **2**
- Many-to-many links: **1** (Task↔Label via `task_labels`)
- Entities requiring auth: **3**
- Entities owner-scoped: **2**
- Entities with encrypted fields: **0**

## Entities

### Project  (`projects`)
- Security: auth, owner=user_id
- Indexed (owner/external, no FK): `user_id`
- Workflow: yes

### Task  (`tasks`)
- Security: auth, owner=user_id
- Foreign keys: `project_id` → `projects`
- Indexed (owner/external, no FK): `user_id`
- Workflow: yes
- Reference rule: `project_id` must reference an existing `Project` with status in ['active']

### Label  (`labels`)
- Security: auth
- Workflow: no

## Workflows

### Project.status (initial: `active`)
- `active` → `archived`
- `archived` → `active`

### Task.status (initial: `todo`)
- `todo` → `doing`, `cancelled`
- `doing` → `todo`, `blocked`, `done`, `cancelled`
- `blocked` → `doing`, `cancelled`
- `done` → 
- `cancelled` → `todo`

## Enforced by generation

- Per-entity tables with primary keys and Alembic-compatible models.
- Client-supplied <entity>_id columns are real FOREIGN KEYs (+ index); orphaned references are rejected (409).
- Server-set owner columns (user_id) are indexed; ownership is forced from the authenticated principal.
- Declared state machines: only listed transitions are allowed; target-state guards must hold; violations return 409.
- Auth / owner-scoping / field encryption / audit per the entity's data-sensitivity policy.

## NOT enforced (by design, this build)

- many-to-many is now generated from a domain many_to_many declaration (join table with two CASCADE FKs + a uniqueness constraint, plus a link service and attach/detach/list routes) — proven by the many_to_many contract + HTTP e2e; still pending: relationships are otherwise inferred from <entity>_id naming (one-to-many / many-to-one), and richer declared relationship metadata (named roles, through-attributes on the join row) is not generated
- still pending: guards now support same-row (field==value) AND cross-entity (related row status) checks; what remains is SIDE EFFECTS on transition (e.g. a damaged return auto-creating an incident + maintenance record and locking the tool), time-based transitions, and notifications
