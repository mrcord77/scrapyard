# Verification Coverage

_Computed across 172 capabilities. Dimensions are measured, not asserted._

- **Behavior-verified:** 172/172 (100%) — passing behavior contract
- **Workflow-verified:** 7/172 (4%) — required by a verified workflow
- **Runtime-verified:** 14/172 (8%) — exercised by the generated-app boot path
- **Security-verified:** 30/30 of security-relevant capabilities

Behavior coverage is near-total; workflow and runtime coverage are intentionally
narrower (they reflect which caps a verified workflow or the boot path actually
touches), which is where verification depth still has room to grow.
