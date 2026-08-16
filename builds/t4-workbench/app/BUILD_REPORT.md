# Build report — AI Research Workbench

Domain `research_workbench` · data sensitivity **moderate**.

_Generated from the resolved domain; describes what the code generators actually emitted._

## Summary

- Entities: **5**
- Relationships with enforced foreign keys: **1**
- Workflows (state machines): **3**
- Many-to-many links: **2** (ResearchDoc↔Tag via `research_doc_tags`, Experiment↔Tag via `experiment_tags`)
- Entities requiring auth: **5**
- Entities owner-scoped: **4**
- Entities with encrypted fields: **0**

## Entities

### ResearchDoc  (`research_docs`)
- Security: auth, owner=user_id
- Indexed (owner/external, no FK): `user_id`
- Workflow: yes

### Note  (`notes`)
- Security: auth, owner=user_id
- Indexed (owner/external, no FK): `user_id`, `doc_id`
- Workflow: no
- Reference rule: `doc_id` must reference an existing `ResearchDoc` with status in ['inbox', 'reading', 'annotated']

### Experiment  (`experiments`)
- Security: auth, owner=user_id
- Indexed (owner/external, no FK): `user_id`
- Workflow: yes

### Run  (`runs`)
- Security: auth, owner=user_id
- Foreign keys: `experiment_id` → `experiments`
- Indexed (owner/external, no FK): `user_id`
- Workflow: yes
- Reference rule: `experiment_id` must reference an existing `Experiment` with status in ['running', 'analyzing']

### Tag  (`tags`)
- Security: auth
- Workflow: no

## Workflows

### ResearchDoc.status (initial: `inbox`)
- `inbox` → `reading`, `archived`
- `reading` → `annotated`, `archived`
- `annotated` → `archived`
- `archived` → `inbox`

### Experiment.status (initial: `draft`)
- `draft` → `running`, `abandoned`
- `running` → `analyzing`, `failed`, `abandoned`
- `analyzing` → `concluded`, `running`
- `concluded` → 
- `failed` → `draft`
- `abandoned` → `draft`

### Run.status (initial: `queued`)
- `queued` → `executing`, `cancelled`
- `executing` → `succeeded`, `failed`, `cancelled`
- `succeeded` → 
- `failed` → `queued`
- `cancelled` → 

## Enforced by generation

- Per-entity tables with primary keys and Alembic-compatible models.
- Client-supplied <entity>_id columns are real FOREIGN KEYs (+ index); orphaned references are rejected (409).
- Server-set owner columns (user_id) are indexed; ownership is forced from the authenticated principal.
- Declared state machines: only listed transitions are allowed; target-state guards must hold; violations return 409.
- Auth / owner-scoping / field encryption / audit per the entity's data-sensitivity policy.

## NOT enforced (by design, this build)

- many-to-many is now generated from a domain many_to_many declaration (join table with two CASCADE FKs + a uniqueness constraint, plus a link service and attach/detach/list routes) — proven by the many_to_many contract + HTTP e2e; still pending: relationships are otherwise inferred from <entity>_id naming (one-to-many / many-to-one), and richer declared relationship metadata (named roles, through-attributes on the join row) is not generated
- still pending: guards now support same-row (field==value) AND cross-entity (related row status) checks; what remains is SIDE EFFECTS on transition (e.g. a damaged return auto-creating an incident + maintenance record and locking the tool), time-based transitions, and notifications
