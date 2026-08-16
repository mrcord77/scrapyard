# Failure simulation

Scenarios whose triggers are present in this build.

## S2 [medium/UNMITIGATED] Email provider outage
- Expected failure: users can't reset/verify
- Safeguards present: none
- **Missing safeguards: queues, retries**
- Detect via: send-failure rate  •  Recover: retry queue; switch provider

## S4 [high/OK] DB connection pool exhausted under load
- Expected failure: requests time out
- Safeguards present: rate_limiting
- Detect via: active-connection metric  •  Recover: raise pool / add replica

## S6 [medium/UNMITIGATED] User cancels subscription but keeps active session
- Expected failure: continued access after downgrade
- Safeguards present: none
- **Missing safeguards: feature_gates, entitlement_gate**
- Detect via: entitlement mismatch  •  Recover: re-check entitlements on each gated action
