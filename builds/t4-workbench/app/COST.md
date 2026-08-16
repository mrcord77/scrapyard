# Cost & scale projection (ESTIMATES)

Order-of-magnitude monthly USD for planning only — not a quote.

| Users | Est. monthly |
|---|---|
| 10 | $15 |
| 100 | $19 |
| 1,000 | $58 |
| 100,000 | $4,315 |

## Cost drivers
- **llm_client** — base $0/mo + $40/1k users — token cost dominates; usage-driven
- **db_session** — base $15/mo + $2/1k users — managed Postgres baseline + storage
- **email** — base $0/mo + $1/1k users — transactional email per-send