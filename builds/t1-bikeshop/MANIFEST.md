# Build: t1-bikeshop

- **Difficulty:** tier1 · **Pattern:** web_application · **Domain:** bikeshop
- **Assembly path:** eos
- **States:** generated=True bootable=True functional=True validated=True
- **Adjudicated checks:** 18 passed / 1 true failures
- **Factory leverage:** over 75% · **Builder intervention:** 0/10

RBAC lifecycle proven 8/8: non-admin 403, grant/promote/revoke via /admin/roles, anon 401

Artifacts: `eos.log`/`assemble.log`, `boot.log`, `smoke.log`, `smoke_results.json`,
`adjudicated.json`, generated app under `app/` (BUILD_REPORT.md, CAPABILITIES.md,
BUILD_PLAN.md inside).
