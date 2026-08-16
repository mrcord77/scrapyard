# Scrapyard Factory Test Report

**Campaign:** 2026-08-16 · **Repo:** `github.com/mrcord77/scrapyard` @ `bc8c18b6939e` (clean clone of `main`)
**Method:** 15 applications built through Scrapyard's own assembly machinery (EOS → resolver → templates → parts), each independently booted and exercised over real HTTP by a harness that reads only the app's OpenAPI contract. Findings adjudicated against each build's *declared* per-entity policy (`build_report.json`), so a check only counts as a failure when the app violates its own contract. Machine-readable results: `factory_test_results.json`. Per-build evidence: `builds/<name>/`.

## Headline

**Scrapyard genuinely builds working applications today.** All 15 builds — spanning 5 patterns × 12 domains (2 custom-authored), easy CRUD to encrypted healthcare — **generated on the first or second attempt, booted, and passed functional smoke over real HTTP with zero custom backend code**. The two custom code artifacts in the whole campaign: one 150-line dashboard (by choice) and one 1-line mount fix.

The campaign also found **13 real defects, including 2 critical security defects** that all of Scrapyard's own 582/582-green verification had missed — both in the gap between "part proven in isolation" and "generated app behavior":

1. **Right-to-erasure didn't erase identity** (F5/F6): the generated delete-account route silently hit the part's safe-by-default dry run, reported `{"deleted": true}`, and the "deleted" account could log back in.
2. **DSAR export leaked credentials** (F9): `/privacy/export` contained the argon2 password hash and the caller's *live plaintext session token*.

Both are now fixed at the generator/part level with executable regressions (the erasure proof is in `verify_runtime --fullstack`, now 12/12; the export redaction is in the part selftest + `security_regression.py`, 8/8). All 582 part selftests and the full verification suite re-pass after every fix.

## Portfolio

| Build | Tier | Pattern + Domain | G | B | F | V | True fails | Leverage | Intervention |
|---|---|---|---|---|---|---|---|---|---|
| t1-toollib | 1 | basic_saas + tool_library | ✓ | ✓ | ✓ | ✓ | 0 | >75% | 0 |
| t1-tasks | 1 | web_application + **task_tracker (custom)** | ✓ | ✓ | ✓ | ✓ | 0 | >75% | 1 |
| t1-bikeshop | 1 | web_application + bikeshop | ✓ | ✓ | ✓ | ✓ | 0 | >75% | 0 |
| t2-crm | 2 | crm + ev_leads | ✓ | ✓ | ✓ | ✓ | 0 | >75% | 0 |
| t2-education | 2 | course_platform + education | ✓ | ✓ | ✓ | ✓ | 0 | >75% | 0 |
| t2-realestate | 2 | directory_site + real_estate | ✓ | ✓ | ✓ | ✓ | 0 | >75% | 0 |
| t2-ticketing | 2 | ticketing_system + construction | ✓ | ✓ | ✓ | ✓ | 0 | >75% | 0 |
| t2-internal | 2 | internal_tool (template path) | ✓ | ✓ | ✓ | – | 0 | >75% | 0 |
| **A: a-sobriety** | 3 | saas_subscription_app + sobriety | ✓ | ✓ | ✓ | ✓ | 0 (deep 22/22) | >75% | 2 |
| **B: b-healthcare** | 3 | saas_subscription_app + healthcare | ✓ | ✓ | ✓ | ✓ | 0 (deep 18/18) | >75% | 2 |
| **C: c-saas** | 3 | saas_subscription_app + saas | ✓ | ✓ | ✓ | ✓ | 0 | >75% | 1 |
| t3-marketplace | 3 | marketplace + ecommerce (React FE) | ✓ | ✓ | ✓ | ✓ | 0 | >75% | 2 |
| t4-oilgas | 4 | ticketing_system + oil_and_gas | ✓ | ✓ | ✓ | ✓ | 0 | >75% | 0 |
| t4-workbench | 4 | agent_platform + **research_workbench (custom)** | ✓ | ✓ | ✓ | ✓ | 0 | 50–75% | 3 |
| t4-community | 4 | basic_saas + community_platform | ✓ | ✓ | ✓ | ✓ | 0 | >75% | 0 |

G/B/F/V = Generated / Bootable / Functional / Validated, kept strictly separate. t2-internal is Functional-not-Validated only because the template path has no domain entities to run ownership adversarials against.

Depth receipts (not just CRUD):
- **State machines with side effects** (toollib): reservation `requested→approved→reserved→checked_out→returned_damaged`, illegal transition → 409, checkout auto-flips the tool's status, damaged return auto-creates an Incident + MaintenanceRecord.
- **RBAC lifecycle** (bikeshop): non-admin write 403 → bootstrap `roles.grant()` → admin 201 → `/admin/roles/grant` promotes a user (201) → revoke → 403 again; anon on admin API 401, non-admin 403. 8/8.
- **Sobriety deep (22/22)**: journal body encrypted at rest (verified against the raw SQLite bytes), plaintext absent from server logs, ownership isolation, export + NDJSON streaming export, audit trail records journal creation *without* the body, erasure removes the user's rows + identity while the bystander's data survives.
- **Healthcare deep (18/18)**: boot **refuses** without encryption keys (with exact minting instructions); `mrn` encrypted at rest; create/update/delete audited with no PHI in the audit rows; redacted export; real erasure.
- **Research workbench** (custom domain): experiment `draft→running→analyzing→concluded`, runs blocked until the experiment is running (reference rule 409), JSON params/metrics fields, notes rejected on archived docs.
- **Deployment**: 5 Docker images build and serve; c-saas and marketplace ran as full `web + postgres:16 + redis:7` compose stacks; data survived a `docker compose restart web` on Postgres; **production boot inside the container fail-closed** with an itemized list of live stub backends (offline LLM, console email, reference crypto).

## The 13 defects (full list in factory_test_results.json)

Fixed during the campaign (each with a regression, suite re-run green, plus a previously-passing build re-run to check collateral):

- **F5 (critical, generator):** erasure dry-run — `delete_account()` called without `confirm=True`; route lied `deleted: true`; account could re-login. The hardening registry's "proven end-to-end: session revoked" prose had **no executable backing** and was false through the HTTP route.
- **F6 (high, integration):** `DeletionRecord` table never created (lazy in-route import missed boot-time `create_all`) — the real deletion path crashed the moment F5 was fixed. Two defects masking each other.
- **F9 (critical, part):** DSAR export contained the password hash and live session token. Now redacted, with selftest + regression.
- **F1 (high, docs):** generated CAPABILITIES.md claimed "auth + owner-scoped" on every entity; low-sensitivity domains actually generate public CRUD. Labels now derive from the actual effective policy.
- **F11 + F12 (high, dependencies):** one part declared internal modules as pip deps (uninstallable requirements.txt → Docker build failures), and a sweep found **197/582 parts import third-party modules they never declare** — apps only installed because some *other* part declared the package (httpx broke 3 containers). The requirements writer now AST-scans copied sources and unions known pip names.
- **F10 (EOS):** no deployment artifacts on the EOS path (template path only). Now writes Dockerfile/compose/CI.
- **F13 (React):** built assets 404'd under the `/app/` mount (absolute vite base). Now relative.

Open, recommended (not fixed — design decisions that belong to the maintainer):

- **F2:** `low` sensitivity ⇒ anonymous create/update/**delete**. Anon `POST /tools` → 201 on a "basic_saas" build. Public reads are defensible; world-writable is not a sane floor.
- **F3:** creates accept arbitrary state-machine field values (a Member born in state `"smoke-status"` then breaks reference rules).
- **F4:** shared auth-only entities are writable/deletable by any authenticated user (healthcare Encounter, sobriety Meeting).
- **F7:** billing parts materialize but **zero billing routes** are generated; the live Stripe path is also unwired (this one is documented honestly upstream). Build A ships no payment surface — reported per instructions, not papered over.
- **F14:** hardening-registry prose claims aren't executable evidence (F5 proved why that matters).

## Answers to the assessment questions

**1. Can Scrapyard build real applications today?** Yes — 15/15 generated, booted, and functional with essentially zero custom code, including encrypted, audited, owner-isolated privacy-sensitive apps. "Real" stops at product-specific business logic (streak computation, billing checkout, notifications), which is generic-CRUD-plus-workflows territory today — the generator itself says so in CAPABILITIES.md.

**2. Which application types does it handle best?** Entity-centric multi-user web apps with declarative workflows: trackers, CRMs, ticketing, directories, schedulers. The sensitive-data tier (sobriety/healthcare) is its most differentiated capability — encryption-at-rest, audit, export/erasure and fail-closed boot are *default outputs*, which even most hand-built apps don't get right (though F5/F9 show that machinery needed exactly this kind of adversarial testing).

**3. Which types expose weaknesses?** Anything needing computation over data (aggregations, scoring, feeds), payments (F7), background/scheduled jobs (sweep endpoints exist but nothing schedules them), real-time features, and search beyond CRUD filters. The agent_platform pattern resolves agent *parts* but generates no agent *behavior* — the workbench is an excellent state-machine app, not an AI product, without custom wiring.

**4. Is EOS genuinely useful?** Yes — it's the best single component. One command yields a bootable app plus honest self-description (BUILD_REPORT, CAPABILITIES, probe metadata) and a gate that correctly *blocked* an under-specified sensitive build (demanding audit_logs for sobriety) and correctly *refused to boot* misconfigured production. Caveat: its per-build "VERIFIED (N behaviors proven)" ran while F5/F9 existed — the self-verification proves boot+CRUD, not the claims in the docs it writes.

**5. Is the resolver useful?** Yes; pattern+domain composition with dependency closure worked in all 15 builds and the closure step repeatedly caught graph gaps. Its weak edge was requirements generation (F11/F12), now closed with the import scan.

**6. Are generated frontends useful?** Usable, not shippable-pretty. The vanilla SPA is contract-coherent (every SPA endpoint resolves against the backend — the fullstack verifier proves this), handles auth+CRUD, and served on every build. React (after F13) and the Jinja dashboard give three presentation styles over the same API; my custom dashboard took ~150 lines against an unmodified API, which is the correct division of labor.

**7. Most-leveraged parts?** The identity stack (users/sessions/auth_routes/password_policy), runtime bootstrap (settings/database/lifespan — the fail-closed production gate lives here), gen_models (entities→models/schemas/services/routes with policies, state machines, reference rules, M2M), pq_field_encryption, audit_logs, and the compliance pair (export/deletion — after their defects were fixed).

**8. Which parts repeatedly caused trouble?** The compliance boundary (account_deletion: F5, F6, F11 — three distinct defects around one part), dependency metadata as a class (F12, 197 parts), and documentation generators overstating security (F1, F14).

**9. How much manual engineering?** Near zero for the apps themselves: two `domain.json` files (declarative spec-writing, the intended path), two request specs, one optional dashboard, one 1-line mount fix, PQ key minting (documented commands). The real engineering went into *fixing Scrapyard* — 8 defect fixes across generators/parts/verifiers, which is precisely what the campaign was for.

**10. Does it materially reduce application-development work?** For its covered class, yes, dramatically: a working owner-isolated encrypted CRUD+workflow app with auth, audit, privacy endpoints, Docker deployment and CI scaffolding in ~90 seconds is weeks of work compressed — *provided* someone reviews the output; this campaign shows what review has to look for.

**11. What is it currently?** Between an **application starter-kit generator** and an **internal app factory** — the honest label is *"internal app factory for entity-centric web apps, with a starter-kit-grade escape hatch."* Not a credible general-purpose app builder yet: business logic, payments, jobs, and search stop at scaffold depth.

**12. Ten highest-value changes to reach the next category:**
1. Wire billing end-to-end: generated checkout/subscription/entitlement routes + real Stripe client (F7) — the gap between "SaaS generator" and "subscription-SaaS generator."
2. Auth-by-default writes at `low` sensitivity (F2).
3. A `derived`/`computed` concept in domains (counts, streaks, aggregates) — the most common custom-code need across all 15 builds.
4. Validate state fields on create against the machine (F3).
5. A job scheduler part wired to the generated sweep endpoints (time transitions currently need an external caller).
6. Make every hardening-registry claim reference an executable check (F14 — F5 hid behind prose).
7. Regenerate part `dependencies` metadata from imports as a catalog gate (F12's 197 parts).
8. Role templates in domains ("staff writes, customers read own") — F4's shared-entity write hole, one declaration away.
9. Auto-wire rate limiting as middleware (the distributed limiter exists, proven, and unused by generated apps — Redis outage was a no-op because nothing routes through it).
10. Unify template & EOS output structure (BUILD_REPORT/probe/verify on the template path too).

## Honest limitations of this campaign

Local models were not usable for this work (interactive debugging of a foreign codebase); everything here was queen-tier work, appropriate for a one-off adversarial validation. SQLite backed most builds — Postgres ran two full stacks; the remaining builds' PG behavior is inferred from shared runtime code, not proven. Production posture was proven *fail-closed*, not proven *operational* (no citadel/SMTP/LLM backends were available, by design of this environment). The generated apps' load behavior, migrations-at-scale, and multi-instance coordination were not tested. All fixes live on the local clone — branch + push instructions below.

## Evidence index

- `factory_test_results.json` — machine-readable per-build states, scores, defects
- `builds/<name>/MANIFEST.md` + `eos.log` + `smoke.log` + `smoke_results.json` + `adjudicated.json` + `deep_test.py`/`deep_results.json` (A, B) + `app/` (generated source incl. BUILD_REPORT.md)
- `.campaign/` — harness (`smoke.py`, `analyze.py`), phase-0 logs (before + after fixes)
- Scrapyard source changes: `tools/eos.py`, `tools/gen_models.py`, `tools/assemble.py`, `tools/gen_frontend_react.py`, `tools/verify_runtime.py`, `scrapyard/runtime/database.py`, `scrapyard/compliance/data_export.py`, `scrapyard/compliance/account_deletion.py`, `scrapyard/security/password_policy.py`, `tests/security_regression.py` (+2 checks), `domains/task_tracker/`, `domains/research_workbench/`, `specs/examples/healthcare_portal.json`
