# Build: a-sobriety

- **Difficulty:** tier3 · **Pattern:** saas_subscription_app · **Domain:** sobriety
- **Assembly path:** eos --request (gated)
- **States:** generated=True bootable=True functional=True validated=True
- **Adjudicated checks:** 58 passed / 0 true failures
- **Factory leverage:** over 75% · **Builder intervention:** 2/10

DEEP 22/22: journal encrypted at rest (raw-DB proven), logs clean, export+stream, audit no-leak, erasure real after FIX of dry-run defect; billing routes NOT generated (Stripe path also unwired upstream — honest limitation)

Artifacts: `eos.log`/`assemble.log`, `boot.log`, `smoke.log`, `smoke_results.json`,
`adjudicated.json`, generated app under `app/` (BUILD_REPORT.md, CAPABILITIES.md,
BUILD_PLAN.md inside).
