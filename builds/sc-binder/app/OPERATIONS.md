# Operational review

Operationally-significant parts in this build and what they demand in production.

## full_text_search
- **Cost:** low (pg) to high (search cluster)
- **Scaling limit:** pg FTS relevance/scale limited; cluster is heavy to run
- **Failure modes:** stale index, poor relevance
- **Monitor:** index lag, query latency
- **Backup:** reindex from source  •  **Recovery:** rebuild index
- **Recommended stage:** growth  •  **Avoid when:** a simple filter query is enough
