# Architecture decisions

- Pattern: **documentation_site**
- Domain: **iep_binder**
- Stage: **growth**
- Date: 2026-08-16

## Strategy choices

### full_text_search: chose **Postgres full-text** (score 3.67 @ growth)
- Why: No extra service; fine for moderate corpora; limited relevance tuning.
- Alternatives: OpenSearch / Elasticsearch (3.33)
