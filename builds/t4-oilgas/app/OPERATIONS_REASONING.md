# Operational reasoning

```
OPERATIONAL REASONING — ticketing_system+oil_and_gas

External dependencies in play: db_session, smtp_provider

Failure reasoning (each external dep that this build leans on):
  db_session [high] -> breaks in-plan: email_verification, password_reset, session_manager, auth_routes, app_factory
      recover: raise pool size; add read replica; shed load via rate_limiting
  smtp_provider [medium] -> breaks in-plan: email, email_verification, password_reset
      recover: retry queue; failover provider; in-app fallback notice

Estimated operational burden: 3 moving parts needing monitoring/runbooks
```
