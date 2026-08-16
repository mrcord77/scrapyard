# Domain: AI Research Workbench

## Entities to scaffold
- **ResearchDoc**: id, user_id, title, source_url, content, status
- **Note**: id, user_id, doc_id, body, kind
- **Experiment**: id, user_id, name, hypothesis, status
- **Run**: id, user_id, experiment_id, params, metrics, status
- **Tag**: id, name

## Workflows
- ingest doc -> read -> annotate (notes) -> archive
- draft experiment -> run (params) -> record metrics -> conclude
