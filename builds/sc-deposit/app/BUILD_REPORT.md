# Build report — Deposit Shield

Domain `deposit_shield` · data sensitivity **moderate**.

_Generated from the resolved domain; describes what the code generators actually emitted._

## Summary

- Entities: **4**
- Relationships with enforced foreign keys: **3**
- Workflows (state machines): **2**
- Many-to-many links: **0**
- Entities requiring auth: **4**
- Entities owner-scoped: **4**
- Entities with encrypted fields: **0**

## Entities

### Tenancy  (`tenancies`)
- Security: auth, owner=user_id
- Indexed (owner/external, no FK): `user_id`
- Workflow: yes

### EvidenceShot  (`evidence_shots`)
- Security: auth, owner=user_id
- Foreign keys: `tenancy_id` → `tenancies`
- Indexed (owner/external, no FK): `user_id`
- Workflow: no
- Reference rule: `tenancy_id` must reference an existing `Tenancy` with status in ['active', 'notice_given', 'moved_out', 'deductions_received', 'disputing']

### Deduction  (`deductions`)
- Security: auth, owner=user_id
- Foreign keys: `tenancy_id` → `tenancies`
- Indexed (owner/external, no FK): `user_id`
- Workflow: yes

### DisputeLetter  (`dispute_letters`)
- Security: auth, owner=user_id
- Foreign keys: `tenancy_id` → `tenancies`
- Indexed (owner/external, no FK): `user_id`
- Workflow: no

## Workflows

### Tenancy.status (initial: `active`)
- `active` → `notice_given`
- `notice_given` → `moved_out`
- `moved_out` → `deposit_returned`, `deductions_received`
- `deductions_received` → `disputing`, `accepted`
- `disputing` → `resolved_full`, `resolved_partial`, `small_claims`
- `small_claims` → `resolved_full`, `resolved_partial`, `lost`
- `deposit_returned` → 
- `accepted` → 
- `resolved_full` → 
- `resolved_partial` → 
- `lost` → 

### Deduction.status (initial: `contested`)
- `contested` → `dropped`, `upheld`, `accepted`
- `dropped` → 
- `upheld` → 
- `accepted` → 

## Enforced by generation

- Per-entity tables with primary keys and Alembic-compatible models.
- Client-supplied <entity>_id columns are real FOREIGN KEYs (+ index); orphaned references are rejected (409).
- Server-set owner columns (user_id) are indexed; ownership is forced from the authenticated principal.
- Declared state machines: only listed transitions are allowed; target-state guards must hold; violations return 409.
- Auth / owner-scoping / field encryption / audit per the entity's data-sensitivity policy.

## NOT enforced (by design, this build)

- many-to-many is now generated from a domain many_to_many declaration (join table with two CASCADE FKs + a uniqueness constraint, plus a link service and attach/detach/list routes) — proven by the many_to_many contract + HTTP e2e; still pending: relationships are otherwise inferred from <entity>_id naming (one-to-many / many-to-one), and richer declared relationship metadata (named roles, through-attributes on the join row) is not generated
- still pending: guards now support same-row (field==value) AND cross-entity (related row status) checks; what remains is SIDE EFFECTS on transition (e.g. a damaged return auto-creating an incident + maintenance record and locking the tool), time-based transitions, and notifications
