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

## llm_client
- **Cost:** per-token, can dominate the bill
- **Scaling limit:** provider rate limits; budget caps
- **Failure modes:** provider outage, rate-limit 429, cost runaway
- **Monitor:** token spend, error rate, latency
- **Backup:** n/a (stateless)  •  **Recovery:** retry with backoff; fall back to a cheaper model
- **Recommended stage:** scale  •  **Avoid when:** a deterministic rule would do the job
