# Build: t1-toollib — Community Tool Library

- **Difficulty:** Tier 1 (easy)
- **Pattern:** basic_saas · **Domain:** tool_library (data_sensitivity: low)
- **Assembly path:** EOS end-to-end (`tools/eos.py --pattern basic_saas --domain tool_library --gate`)
- **Entities:** Member, Tool, Reservation (state machine + no-overlap + reference rules), Incident, MaintenanceRecord, Tag (M2M with Tool)
- **Scrapyard parts:** 41 materialized (auth stack, sessions, rate limiting, security headers, migrations, pagination, soft delete, frontend SPA, health, ...)
- **Custom code written:** ZERO. 100% generated.

## States
- Generated: YES (first attempt, no intervention)
- Bootable: YES (uvicorn, /healthz ok, SPA at /app/)
- Functional: YES — smoke 43/43 over real HTTP; full reservation lifecycle
  (requested→approved→reserved→checked_out→returned_damaged) with guards,
  409 on illegal transition, auto side-effects (tool status flip, auto-created
  Incident + MaintenanceRecord)
- Validated: YES within declared policy — auth flow adversarials pass
  (duplicate reg 409, malformed payload 422, stale session 401); data survives
  process restart (SQLite)

## Findings
- **F1 (FIXED, cat 3 contract/doc):** CAPABILITIES.md claimed "auth + owner-scoped"
  for ALL entities; low-sensitivity actually generates PUBLIC CRUD. Fixed in
  tools/eos.py (policy_label from gen_models.effective_policies) + regression
  test in tests/security_regression.py. Was: false generated security claim.
- **F2 (OPEN, cat 12 hardening default):** low sensitivity ⇒ anonymous
  create/update/DELETE allowed. Anon POST /tools → 201, anon DELETE → 204.
  Public read is defensible for a directory; world-writable is a bad default
  for a "basic_saas" pattern. Recommend: reads public, writes auth at low tier.
- **F3 (OPEN, cat 6 generator):** create accepts arbitrary values for
  state-machine fields (Member created with status "smoke-status", a state not
  in the machine), which then breaks reference rules downstream.

## Scores (0-10)
assembly=10 boot=10 functional=9 reuse=10 custom-code=10(none needed)
frontend=7(generic SPA, usable) data-model=9 security=4(open-by-design but F2/F3)
ops=7 deploy=untested-yet
- Factory leverage: **over 75%** (100% of code generated)
- Builder intervention: **0** (zero manual engineering for the app itself)
