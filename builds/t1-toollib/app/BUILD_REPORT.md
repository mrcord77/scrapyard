# Build report — Community Tool Library

Domain `tool_library` · data sensitivity **low**.

_Generated from the resolved domain; describes what the code generators actually emitted._

## Summary

- Entities: **6**
- Relationships with enforced foreign keys: **5**
- Workflows (state machines): **4**
- Many-to-many links: **1** (Tool↔Tag via `tool_tags`)
- Entities requiring auth: **0**
- Entities owner-scoped: **0**
- Entities with encrypted fields: **0**

## Entities

### Member  (`members`)
- Security: no-auth
- Workflow: yes

### Tool  (`tools`)
- Security: no-auth
- Workflow: yes

### Reservation  (`reservations`)
- Security: no-auth
- Foreign keys: `member_id` → `members`; `tool_id` → `tools`
- Workflow: yes
- Reference rule: `member_id` must reference an existing `Member` with status in ['active']
- Reference rule: `tool_id` must reference an existing `Tool` with status in ['available']
- No-overlap: rows sharing `tool_id` cannot overlap on [`start_at`,`end_at`) while active
- Cross-entity guard: transition requires `Tool` (via `tool_id`) status in ['available', 'reserved']
- Cross-entity guard: transition requires `Member` (via `member_id`) status in ['active']
- On `checked_out`: set `Tool.status` = `checked_out` (via `tool_id`) (guarded — routed through the target's own transition)
- On `returned`: set `Tool.status` = `available` (via `tool_id`) (guarded — routed through the target's own transition)
- On `returned_damaged`: set `Tool.status` = `maintenance` (via `tool_id`) (guarded — routed through the target's own transition)
- On `returned_damaged`: auto-create a `Incident` record
- On `returned_damaged`: auto-create a `MaintenanceRecord` record
- Time-based: a `requested` row auto-advances to `expired` once `end_at` has passed (via `POST /reservations/sweep`)
- Time-based: a `approved` row auto-advances to `expired` once `end_at` has passed (via `POST /reservations/sweep`)
- Time-based: a `reserved` row auto-advances to `expired` once `end_at` has passed (via `POST /reservations/sweep`)

### Incident  (`incidents`)
- Security: no-auth
- Foreign keys: `tool_id` → `tools`; `reservation_id` → `reservations`
- Workflow: no

### MaintenanceRecord  (`maintenance_records`)
- Security: no-auth
- Foreign keys: `tool_id` → `tools`
- Workflow: yes
- On `completed`: set `Tool.status` = `available` (via `tool_id`) (guarded — routed through the target's own transition)

### Tag  (`tags`)
- Security: no-auth
- Workflow: no

## Workflows

### Member.status (initial: `active`)
- `active` → `suspended`, `expired`, `banned`
- `suspended` → `active`
- `expired` → `active`
- `banned` → 

### Tool.status (initial: `available`)
- `available` → `reserved`, `checked_out`, `maintenance`, `broken`, `retired`
- `reserved` → `available`, `checked_out`
- `checked_out` → `available`, `maintenance`, `broken`
- `maintenance` → `available`, `retired`
- `broken` → `maintenance`, `retired`

### Reservation.status (initial: `requested`)
- `requested` → `approved`, `cancelled`, `denied`, `expired`
- `approved` → `reserved`, `cancelled`, `expired`
- `reserved` → `checked_out`, `cancelled`, `expired`
- `checked_out` → `returned`, `returned_damaged`
- `returned` → 
- `returned_damaged` → 
- `cancelled` → 
- `denied` → 
- `expired` → 
  - entering `checked_out` requires `status` == `None` — else: cannot check out: tool is not available
  - entering `checked_out` requires `status` == `None` — else: cannot check out: member is not active

### MaintenanceRecord.status (initial: `open`)
- `open` → `completed`
- `completed` → 

## Enforced by generation

- Per-entity tables with primary keys and Alembic-compatible models.
- Client-supplied <entity>_id columns are real FOREIGN KEYs (+ index); orphaned references are rejected (409).
- Server-set owner columns (user_id) are indexed; ownership is forced from the authenticated principal.
- Declared state machines: only listed transitions are allowed; target-state guards must hold; violations return 409.
- Auth / owner-scoping / field encryption / audit per the entity's data-sensitivity policy.

## NOT enforced (by design, this build)

- many-to-many is now generated from a domain many_to_many declaration (join table with two CASCADE FKs + a uniqueness constraint, plus a link service and attach/detach/list routes) — proven by the many_to_many contract + HTTP e2e; still pending: relationships are otherwise inferred from <entity>_id naming (one-to-many / many-to-one), and richer declared relationship metadata (named roles, through-attributes on the join row) is not generated
- still pending: guards now support same-row (field==value) AND cross-entity (related row status) checks; what remains is SIDE EFFECTS on transition (e.g. a damaged return auto-creating an incident + maintenance record and locking the tool), time-based transitions, and notifications
