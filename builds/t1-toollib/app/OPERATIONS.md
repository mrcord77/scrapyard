# Operational review

Operationally-significant parts in this build and what they demand in production.

## db_session
- **Cost:** core infra
- **Scaling limit:** connection pool exhaustion under spikes
- **Failure modes:** pool exhaustion, long transactions blocking
- **Monitor:** active connections, slow queries
- **Backup:** regular DB snapshots  •  **Recovery:** restore snapshot; failover replica
- **Recommended stage:** mvp  •  **Avoid when:** never — it's foundational

## email
- **Cost:** low per-send; reputation risk
- **Scaling limit:** provider sending limits
- **Failure modes:** bounce/spam, provider outage, silent drops
- **Monitor:** bounce rate, send failures
- **Backup:** queue + retry  •  **Recovery:** retry; switch provider
- **Recommended stage:** growth  •  **Avoid when:** in-app notification suffices
