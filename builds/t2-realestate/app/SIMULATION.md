# Failure simulation

Scenarios whose triggers are present in this build.

## S4 [high/UNMITIGATED] DB connection pool exhausted under load
- Expected failure: requests time out
- Safeguards present: none
- **Missing safeguards: rate_limiting**
- Detect via: active-connection metric  •  Recover: raise pool / add replica
