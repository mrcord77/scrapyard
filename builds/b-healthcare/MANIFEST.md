# Build: b-healthcare

- **Difficulty:** tier3 · **Pattern:** saas_subscription_app · **Domain:** healthcare
- **Assembly path:** eos --request (gated)
- **States:** generated=True bootable=True functional=True validated=True
- **Adjudicated checks:** 23 passed / 1 true failures
- **Factory leverage:** over 75% · **Builder intervention:** 2/10

DEEP 18/18: PHI(mrn) encrypted at rest, audited CRUD, secure boot refusal w/o keys, export redacted after FIX, erasure real; runs as container

Artifacts: `eos.log`/`assemble.log`, `boot.log`, `smoke.log`, `smoke_results.json`,
`adjudicated.json`, generated app under `app/` (BUILD_REPORT.md, CAPABILITIES.md,
BUILD_PLAN.md inside).
