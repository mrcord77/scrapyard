"""
crm_data_export — Export CRM leads and deals to CSV/JSON using the canonical CRM models.

### PART-META-JSON
{
  "name": "crm_data_export",
  "layer": "sales",
  "purpose": "Export CRM pipeline data (leads from crm_lead_management, deals from crm_deal_pipeline) into CSV/JSON for reporting or migration - no duplicate model definitions.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "_configure(engine); export_leads_to_csv(filters: dict) with equality filters on Lead columns; export_deals_to_json(filters: dict) with equality filters on Deal columns.",
  "outputs": "CSV string (name,email,phone,company,status,created_at) and JSON string ([{id,title,stage,created_at}]); models are IMPORTED from scrapyard.sales.crm_lead_management / crm_deal_pipeline.",
  "files_created": [],
  "security_notes": "Filter keys are matched against real model attributes only (unknown keys ignored) and values are bound via SQLAlchemy parameters - no SQL injection path. CSV fields are escaped per RFC 4180 (quotes doubled, fields with commas/quotes/newlines quoted) so a lead named '=cmd|...' cannot break row structure; consumers opening exports in Excel should still guard against formula injection (values are not prefixed). Exports contain lead PII (names, emails, phones) - treat output files as sensitive.",
  "ai_usage": "Import from `scrapyard.sales.crm_data_export`; call _configure(engine) with an engine whose metadata includes the canonical CRM tables.",
  "example": "from scrapyard.sales.crm_data_export import export_leads_to_csv",
  "import_path": "scrapyard.sales.crm_data_export"
}
### END-PART-META
"""
from sqlalchemy import select, create_engine
from sqlalchemy.orm import sessionmaker
from scrapyard.database.base_model import IntPKModel

# Canonical CRM models - owned by their dedicated parts, imported here.
from scrapyard.sales.crm_lead_management import Lead, LeadCreate, create_lead
from scrapyard.sales.crm_deal_pipeline import Deal, DealStage

from typing import Dict, Any
import os, re, json, logging, tempfile

# Setup logger
logger = logging.getLogger(__name__)

STATUS = "core"

# Module-level session factory (unbound initially)
_session_factory = sessionmaker()


def _configure(engine):
    """Configure the module to use the given engine."""
    global _session_factory
    _session_factory = sessionmaker(bind=engine)


def _apply_filters(query, model, filters: Dict[str, Any]):
    """Apply dictionary equality filters to a SQLAlchemy query."""
    for key, value in filters.items():
        if hasattr(model, key):
            query = query.where(getattr(model, key) == value)
    return query


def _csv_field(value: Any) -> str:
    """RFC 4180 escaping: quote fields containing delimiters/quotes/newlines."""
    text = "" if value is None else str(value)
    if any(ch in text for ch in (',', '"', '\n', '\r')):
        return '"' + text.replace('"', '""') + '"'
    return text


def export_leads_to_csv(filters: dict) -> str:
    """Export canonical leads to CSV with equality filters."""
    session = _session_factory()
    try:
        rows = ["name,email,phone,company,status,created_at"]

        query = select(Lead)
        query = _apply_filters(query, Lead, filters)

        for lead in session.execute(query).scalars().all():
            created_at = lead.created_at.isoformat() if lead.created_at else ""
            rows.append(",".join(_csv_field(v) for v in (
                lead.name, lead.email, lead.phone, lead.company, lead.status, created_at
            )))

        return "\n".join(rows) + "\n"
    finally:
        session.close()


def export_deals_to_json(filters: dict) -> str:
    """Export canonical deals to JSON with equality filters; stage is resolved to its name."""
    session = _session_factory()
    try:
        deals = []

        query = select(Deal)
        query = _apply_filters(query, Deal, filters)

        for deal in session.execute(query).scalars().all():
            stage_name = None
            if deal.current_stage_id is not None:
                stage = session.get(DealStage, deal.current_stage_id)
                stage_name = stage.name if stage else None
            deals.append({
                'id': deal.id,
                'title': deal.title,
                'stage': stage_name,
                'created_at': deal.created_at.isoformat() if deal.created_at else None,
            })

        return json.dumps(deals, indent=4)
    finally:
        session.close()


def _selftest() -> None:
    """Self-test module functionality against the canonical CRM models."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')

        # Create SQLAlchemy engine and configure module
        engine = create_engine(f'sqlite:///{db_path}', echo=False)
        _configure(engine)

        # Create tables (shared metadata includes the canonical CRM tables)
        IntPKModel.metadata.create_all(engine)

        session = _session_factory()
        try:
            # Insert test data through the canonical lead API
            lead1 = create_lead(session, LeadCreate(
                name='John Doe', email='john@example.com', phone='1234567890',
                company='Acme, Inc.', status='New'))
            lead2 = create_lead(session, LeadCreate(
                name='Jane Smith', email='jane@example.com', phone='0987654321',
                status='Qualified'))

            stage_neg = DealStage(name='Negotiation', stage_order=1)
            stage_won = DealStage(name='Won', stage_order=2)
            session.add_all([stage_neg, stage_won])
            session.flush()

            deal1 = Deal(title='Big deal', current_stage_id=stage_neg.id)
            deal2 = Deal(title='Small deal', current_stage_id=stage_won.id)
            session.add_all([deal1, deal2])
            session.commit()

            # Export leads to CSV
            csv_content = export_leads_to_csv({'status': 'New'})
            logger.debug(f"CSV export result:\n{csv_content}")

            # Verify CSV content
            assert 'name,email,phone,company,status,created_at' in csv_content
            assert 'John Doe' in csv_content
            assert 'john@example.com' in csv_content
            assert '1234567890' in csv_content
            assert '"Acme, Inc."' in csv_content  # comma-containing field is quoted
            assert 'New' in csv_content
            assert 'Jane Smith' not in csv_content

            # Verify datetime format in CSV (ISO format with T separator)
            assert re.search(r'New,\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', csv_content)

            # Unfiltered export includes both leads; unknown filter keys are ignored
            all_csv = export_leads_to_csv({'not_a_column': 'x'})
            assert 'Jane Smith' in all_csv and 'John Doe' in all_csv

            # Export deals to JSON
            json_content = export_deals_to_json({'current_stage_id': stage_neg.id})
            logger.debug(f"JSON export result:\n{json_content}")

            parsed = json.loads(json_content)
            assert len(parsed) == 1
            assert parsed[0]['title'] == 'Big deal'
            assert parsed[0]['stage'] == 'Negotiation'
            assert 'created_at' in parsed[0]

            all_deals = json.loads(export_deals_to_json({}))
            assert {d['stage'] for d in all_deals} == {'Negotiation', 'Won'}

        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("crm_data_export selftest OK")
