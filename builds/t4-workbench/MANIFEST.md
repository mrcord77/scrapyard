# Build: t4-workbench

- **Difficulty:** tier4 · **Pattern:** agent_platform · **Domain:** research_workbench (CUSTOM)
- **Assembly path:** eos
- **States:** generated=True bootable=True functional=True validated=True
- **Adjudicated checks:** 33 passed / 1 true failures
- **Factory leverage:** 50-75% · **Builder intervention:** 3/10

custom domain; full experiment/run lifecycle + reference rules proven; custom ops dashboard (~150 LOC custom UI)

Artifacts: `eos.log`/`assemble.log`, `boot.log`, `smoke.log`, `smoke_results.json`,
`adjudicated.json`, generated app under `app/` (BUILD_REPORT.md, CAPABILITIES.md,
BUILD_PLAN.md inside).
