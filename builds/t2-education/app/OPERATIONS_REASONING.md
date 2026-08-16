# Operational reasoning

```
OPERATIONAL REASONING — course_platform+education

External dependencies in play: db_session, smtp_provider, stripe_api

Failure reasoning (each external dep that this build leans on):
  db_session [high] -> breaks in-plan: email_verification, password_reset, stripe_webhooks, subscription_status, entitlement_gate, subscriptions, stripe_checkout, session_manager, auth_routes, app_factory
      recover: raise pool size; add read replica; shed load via rate_limiting
  smtp_provider [medium] -> breaks in-plan: email, email_verification, password_reset
      recover: retry queue; failover provider; in-app fallback notice
  stripe_api [high] -> breaks in-plan: stripe_webhooks, stripe_checkout
      recover: queue checkout intents; retry; show degraded billing UI

Estimated operational burden: 4 moving parts needing monitoring/runbooks
```
