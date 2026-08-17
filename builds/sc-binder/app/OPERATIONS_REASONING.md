# Operational reasoning

```
OPERATIONAL REASONING — documentation_site+iep_binder

External dependencies in play: db_session

Failure reasoning (each external dep that this build leans on):
  db_session [high] -> breaks in-plan: account_deletion, data_export, audit_logs, session_manager, auth_routes, app_factory
      recover: raise pool size; add read replica; shed load via rate_limiting

Estimated operational burden: 1 moving parts needing monitoring/runbooks
```
