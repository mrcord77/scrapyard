# Build: c-saas

- **Difficulty:** tier3 · **Pattern:** saas_subscription_app · **Domain:** saas
- **Assembly path:** eos
- **States:** generated=True bootable=True functional=True validated=True
- **Adjudicated checks:** 33 passed / 0 true failures
- **Factory leverage:** over 75% · **Builder intervention:** 1/10

CONTROL: full PG+Redis compose stack; PG persistence across container restart; prod boot fail-closed in-container (stub backends itemized)

Artifacts: `eos.log`/`assemble.log`, `boot.log`, `smoke.log`, `smoke_results.json`,
`adjudicated.json`, generated app under `app/` (BUILD_REPORT.md, CAPABILITIES.md,
BUILD_PLAN.md inside).
