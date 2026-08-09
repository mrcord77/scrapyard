"""
report_template — Canonical report template model for the analytics layer.

### PART-META-JSON
{
  "name": "report_template",
  "layer": "analytics",
  "purpose": "Own the canonical ReportTemplateModel (name, format, content, timestamps) used by BI reporting parts; validate format on creation.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "create_report_template(name: str, format: str, content: str) with format in {PDF, CSV, HTML}.",
  "outputs": "ReportTemplateModel instances (table 'report_template_report_template'); sibling parts (metric_definition) import this model instead of redefining it.",
  "files_created": [],
  "security_notes": "Template content is stored verbatim and is NOT sanitized here; if templates are ever rendered to HTML or fed to a templating engine downstream, the renderer must escape user-controlled values to avoid injection. Format is whitelist-validated (PDF/CSV/HTML). No secrets should be embedded in template content - it is plain text in the DB.",
  "ai_usage": "Import ReportTemplateModel/create_report_template from `scrapyard.analytics.report_template`; call IntPKModel.metadata.create_all(engine) before use.",
  "example": "from scrapyard.analytics.report_template import create_report_template",
  "import_path": "scrapyard.analytics.report_template"
}
### END-PART-META
"""
from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from typing import Optional
import logging, tempfile

logger = logging.getLogger(__name__)

STATUS = "core"


class ReportTemplateModel(IntPKModel):
    __tablename__ = 'report_template_report_template'
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False, server_default='PDF')
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())

def create_report_template(name: str, format: str, content: str) -> ReportTemplateModel:
    if format not in ['PDF', 'CSV', 'HTML']:
        raise ValueError("Invalid format. Must be one of: PDF, CSV, HTML")
    if not name or not content:
        raise ValueError("Name and content are required fields.")
    template = ReportTemplateModel(name=name, format=format, content=content)
    return template

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        # Use SQLAlchemy engine for proper ORM support
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(f'sqlite:///{temp_dir}/test.db')
        IntPKModel.metadata.create_all(engine)

        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        # Create a report template
        template_name = 'Test Report'
        template_format = 'PDF'
        template_content = 'Sample content for the test report.'
        new_template = create_report_template(name=template_name, format=template_format, content=template_content)
        session.add(new_template)
        session.commit()

        # Retrieve and validate the created template
        retrieved_template = session.query(ReportTemplateModel).filter_by(name=template_name).first()
        assert retrieved_template is not None, "Failed to retrieve the report template"
        assert retrieved_template.format == template_format, "Format mismatch in retrieved report template"
        assert retrieved_template.content == template_content, "Content mismatch in retrieved report template"

        # Validate format and content constraints
        try:
            create_report_template(name='Invalid Name', format='INVALID', content='This should fail')
        except ValueError:
            pass  # Expected validation error
        else:
            assert False, "Expected ValueError for invalid format"

        try:
            create_report_template(name='', format='PDF', content='This should fail')
        except ValueError:
            pass  # Expected validation error
        else:
            assert False, "Expected ValueError for empty name"

        try:
            create_report_template(name='Valid Name', format='PDF', content='')
        except ValueError:
            pass  # Expected validation error
        else:
            assert False, "Expected ValueError for empty content"

        # Ensure that the database schema was created (table renamed to
        # '<part>_<table>' by the collision fix - assert the real name)
        with engine.connect() as connection:
            assert connection.dialect.has_table(connection, ReportTemplateModel.__tablename__), \
                f"{ReportTemplateModel.__tablename__} table not created"

        # Ensure that the model has the correct attributes
        assert hasattr(ReportTemplateModel, 'name'), "Missing 'name' attribute in ReportTemplateModel"
        assert hasattr(ReportTemplateModel, 'format'), "Missing 'format' attribute in ReportTemplateModel"
        assert hasattr(ReportTemplateModel, 'content'), "Missing 'content' attribute in ReportTemplateModel"
        assert hasattr(ReportTemplateModel, 'created_at'), "Missing 'created_at' attribute in ReportTemplateModel"
        assert hasattr(ReportTemplateModel, 'updated_at'), "Missing 'updated_at' attribute in ReportTemplateModel"

        # Ensure that the create_report_template function returns an instance of ReportTemplateModel
        assert isinstance(new_template, ReportTemplateModel), "create_report_template did not return ReportTemplateModel"

        # Ensure that the session is closed and engine is disposed
        session.close()
        engine.dispose()

if __name__ == "__main__":
    _selftest()
