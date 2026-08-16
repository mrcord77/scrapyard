# Operational reasoning

```
OPERATIONAL REASONING — agent_platform+research_workbench

External dependencies in play: db_session, llm_client, smtp_provider

Failure reasoning (each external dep that this build leans on):
  db_session [high] -> breaks in-plan: account_deletion, data_export, email_verification, password_reset, session_manager, auth_routes, app_factory
      recover: raise pool size; add read replica; shed load via rate_limiting
  llm_client [high] -> breaks in-plan: embeddings
      recover: backoff+retry; cheaper fallback model; per-tenant budget caps
  smtp_provider [medium] -> breaks in-plan: email, email_verification, password_reset
      recover: retry queue; failover provider; in-app fallback notice

Estimated operational burden: 5 moving parts needing monitoring/runbooks
```
