# Operational review

Operationally-significant parts in this build and what they demand in production.

## db_session
- **Cost:** core infra
- **Scaling limit:** connection pool exhaustion under spikes
- **Failure modes:** pool exhaustion, long transactions blocking
- **Monitor:** active connections, slow queries
- **Backup:** regular DB snapshots  •  **Recovery:** restore snapshot; failover replica
- **Recommended stage:** mvp  •  **Avoid when:** never — it's foundational
