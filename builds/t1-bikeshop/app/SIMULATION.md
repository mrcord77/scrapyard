# Failure simulation

Scenarios whose triggers are present in this build.

## S4 [high/OK] DB connection pool exhausted under load
- Expected failure: requests time out
- Safeguards present: rate_limiting
- Detect via: active-connection metric  •  Recover: raise pool / add replica
