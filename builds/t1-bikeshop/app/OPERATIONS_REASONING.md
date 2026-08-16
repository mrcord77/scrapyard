# Operational reasoning

```
OPERATIONAL REASONING — web_application+bikeshop

External dependencies in play: db_session

Failure reasoning (each external dep that this build leans on):
  db_session [high] -> breaks in-plan: session_manager, auth_routes, app_factory
      recover: raise pool size; add read replica; shed load via rate_limiting

Estimated operational burden: 2 moving parts needing monitoring/runbooks
```
