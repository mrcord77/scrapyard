# Build report — Overturn

Domain `appeal_fighter` · data sensitivity **high**.

_Generated from the resolved domain; describes what the code generators actually emitted._

## Summary

- Entities: **5**
- Relationships with enforced foreign keys: **4**
- Workflows (state machines): **2**
- Many-to-many links: **0**
- Entities requiring auth: **5**
- Entities owner-scoped: **5**
- Entities with encrypted fields: **5**

## Entities

### Claim  (`claims`)
- Security: auth, owner=user_id, encrypted=service, audit=create,update,delete
- Indexed (owner/external, no FK): `user_id`
- Workflow: yes

### Denial  (`denials`)
- Security: auth, owner=user_id, encrypted=reason_text, audit=create,delete
- Foreign keys: `claim_id` → `claims`
- Indexed (owner/external, no FK): `user_id`
- Workflow: no
- Reference rule: `claim_id` must reference an existing `Claim` with status in ['submitted', 'denied', 'internal_appeal', 'upheld', 'external_review']

### Appeal  (`appeals`)
- Security: auth, owner=user_id, encrypted=argument, audit=create,update,delete
- Foreign keys: `claim_id` → `claims`
- Indexed (owner/external, no FK): `user_id`
- Workflow: yes
- Reference rule: `claim_id` must reference an existing `Claim` with status in ['denied', 'internal_appeal', 'upheld', 'external_review']

### EvidenceItem  (`evidence_items`)
- Security: auth, owner=user_id, encrypted=body, audit=create,delete
- Foreign keys: `claim_id` → `claims`
- Indexed (owner/external, no FK): `user_id`
- Workflow: no
- Reference rule: `claim_id` must reference an existing `Claim` with status in ['submitted', 'denied', 'internal_appeal', 'upheld', 'external_review', 'overturned']

### CallLog  (`call_logs`)
- Security: auth, owner=user_id, encrypted=summary, audit=create,update,delete
- Foreign keys: `claim_id` → `claims`
- Indexed (owner/external, no FK): `user_id`
- Workflow: no

## Workflows

### Claim.status (initial: `submitted`)
- `submitted` → `paid`, `denied`
- `denied` → `internal_appeal`, `abandoned`
- `internal_appeal` → `overturned`, `upheld`, `abandoned`
- `upheld` → `external_review`, `abandoned`
- `external_review` → `overturned`, `final_denial`
- `overturned` → `paid`
- `paid` → 
- `final_denial` → 
- `abandoned` → `denied`

### Appeal.status (initial: `drafting`)
- `drafting` → `filed`
- `filed` → `won`, `lost`, `no_response`
- `won` → 
- `lost` → 
- `no_response` → `filed`

## Enforced by generation

- Per-entity tables with primary keys and Alembic-compatible models.
- Client-supplied <entity>_id columns are real FOREIGN KEYs (+ index); orphaned references are rejected (409).
- Server-set owner columns (user_id) are indexed; ownership is forced from the authenticated principal.
- Declared state machines: only listed transitions are allowed; target-state guards must hold; violations return 409.
- Auth / owner-scoping / field encryption / audit per the entity's data-sensitivity policy.

## NOT enforced (by design, this build)

- many-to-many is now generated from a domain many_to_many declaration (join table with two CASCADE FKs + a uniqueness constraint, plus a link service and attach/detach/list routes) — proven by the many_to_many contract + HTTP e2e; still pending: relationships are otherwise inferred from <entity>_id naming (one-to-many / many-to-one), and richer declared relationship metadata (named roles, through-attributes on the join row) is not generated
- still pending: guards now support same-row (field==value) AND cross-entity (related row status) checks; what remains is SIDE EFFECTS on transition (e.g. a damaged return auto-creating an incident + maintenance record and locking the tool), time-based transitions, and notifications
