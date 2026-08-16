# Cost & scale projection (ESTIMATES)

Order-of-magnitude monthly USD for planning only — not a quote.

| Users | Est. monthly |
|---|---|
| 10 | $15 |
| 100 | $15 |
| 1,000 | $18 |
| 100,000 | $315 |

## Cost drivers
- **db_session** — base $15/mo + $2/1k users — managed Postgres baseline + storage
- **email** — base $0/mo + $1/1k users — transactional email per-send
- **stripe_checkout** — base $0/mo + $0/1k users — Stripe takes a % of revenue, not per-user infra