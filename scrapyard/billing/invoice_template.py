"""
invoice_template - Store versioned invoice templates and render invoices through pluggable format renderers.

### PART-META-JSON
{
  "name": "invoice_template",
  "layer": "billing",
  "purpose": "Store versioned invoice templates and render invoices through pluggable format renderers.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "configure(engine); register_renderer(format_type, renderer); render_invoice_template(invoice_id).",
  "outputs": "InvoiceTemplate / TemplateVersion rows (tables 'invoice_template' / 'template_version'); rendered invoice strings.",
  "files_created": [],
  "security_notes": "Renderers are registered in code, not loaded from data. Template content is stored verbatim; if HTML templates are rendered for customers, the renderer must escape injected invoice values to prevent markup injection. No secrets belong in template bodies.",
  "ai_usage": "Import what you need from `scrapyard.billing.invoice_template`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.billing.invoice_template import render_invoice_template",
  "import_path": "scrapyard.billing.invoice_template"
}
### END-PART-META
"""
from __future__ import annotations

import html
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, sessionmaker

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

_TOKEN_RE: re.Pattern[str] = re.compile(r"\{\{\s*(\w+)\s*\}\}")

_ENGINE: Optional[Engine] = None
_SESSION_MAKER: Optional[sessionmaker[Session]] = None

_Renderer = Callable[[str, Dict[str, Any]], str]
_RENDERERS: Dict[str, _Renderer] = {}


class InvoiceTemplate(IntPKModel):
    """Metadata for a reusable invoice template."""

    __tablename__ = "invoice_template"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    format_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="text", server_default="text"
    )
    is_active: Mapped[bool] = mapped_column(
        default=True, nullable=False, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    versions: Mapped[List["TemplateVersion"]] = relationship(
        "TemplateVersion",
        back_populates="template",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_invoice_template_active", "is_active"),)


class TemplateVersion(IntPKModel):
    """A versioned snapshot of invoice template content."""

    __tablename__ = "template_version"

    template_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_template.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        default=False, nullable=False, server_default="0"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    template: Mapped["InvoiceTemplate"] = relationship(
        "InvoiceTemplate", back_populates="versions"
    )

    __table_args__ = (
        UniqueConstraint("template_id", "version_number"),
        Index("ix_template_version_active", "template_id", "is_active"),
    )


def configure(engine: Engine) -> None:
    """Bind the module to a SQLAlchemy engine."""
    global _ENGINE, _SESSION_MAKER
    _ENGINE = engine
    _SESSION_MAKER = sessionmaker(bind=engine, class_=Session)


def register_renderer(format_type: str, renderer: _Renderer) -> None:
    """Register a renderer for an invoice format (e.g. pdf, email)."""
    _RENDERERS[format_type] = renderer


def _render_text(content: str, data: Dict[str, Any]) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = data.get(key)
        return "" if value is None else str(value)

    return _TOKEN_RE.sub(_replace, content)


def _render_html(content: str, data: Dict[str, Any]) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = data.get(key)
        return "" if value is None else html.escape(str(value))

    return _TOKEN_RE.sub(_replace, content)


register_renderer("text", _render_text)
register_renderer("html", _render_html)
register_renderer("email", _render_html)
register_renderer("pdf", _render_text)


def _sample_invoice(invoice_id: int) -> Dict[str, Any]:
    return {
        "invoice_id": invoice_id,
        "customer": "Sample Customer",
        "date": datetime.now(timezone.utc).isoformat(),
        "items": "Widget A x2 @ $50.00",
        "total": "100.00",
    }


def _get_session() -> Session:
    if _SESSION_MAKER is None:
        raise RuntimeError(
            "scrapyard.billing.invoice_template is not configured with a database engine"
        )
    return _SESSION_MAKER()


def render_invoice_template(invoice_id: int) -> str:
    """
    Render the currently active invoice template for the given invoice id.

    The active template is the one where both ``InvoiceTemplate.is_active``
    and a linked ``TemplateVersion.is_active`` are true.
    """
    session = _get_session()
    try:
        stmt = (
            select(InvoiceTemplate, TemplateVersion)
            .join(
                TemplateVersion,
                InvoiceTemplate.id == TemplateVersion.template_id,
            )
            .where(InvoiceTemplate.is_active.is_(True))
            .where(TemplateVersion.is_active.is_(True))
        )
        row: Optional[Tuple[InvoiceTemplate, TemplateVersion]] = session.execute(
            stmt
        ).first()
        if row is None:
            raise ValueError("No active invoice template is configured")
        template, version = row
        renderer = _RENDERERS.get(template.format_type, _render_text)
        return renderer(version.content, _sample_invoice(invoice_id))
    finally:
        session.close()


def _selftest() -> None:
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        db_path = os.path.join(tmpdir.name, "invoice_template_selftest.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)

        InvoiceTemplate.metadata.create_all(engine)
        configure(engine)

        with _get_session() as session:
            template = InvoiceTemplate(
                name="Selftest Invoice",
                description="A template created by the self-test",
                format_type="text",
                is_active=True,
            )
            session.add(template)
            session.flush()

            version = TemplateVersion(
                template_id=template.id,
                version_number=1,
                content=(
                    "Invoice #{{ invoice_id }}\n"
                    "Customer: {{ customer }}\n"
                    "Items: {{ items }}\n"
                    "Total: ${{ total }}"
                ),
                is_active=True,
            )
            session.add(version)
            session.commit()

        with _get_session() as session:
            fetched = session.execute(
                select(InvoiceTemplate).where(
                    InvoiceTemplate.name == "Selftest Invoice"
                )
            ).scalar_one()
            assert fetched.format_type == "text"
            assert fetched.is_active is True

        rendered = render_invoice_template(12345)
        assert isinstance(rendered, str)
        assert "12345" in rendered
        assert "Sample Customer" in rendered
        assert "$100.00" in rendered

        with _get_session() as session:
            versions = session.execute(
                select(TemplateVersion).where(
                    TemplateVersion.template_id == fetched.id
                )
            ).scalars().all()
            assert len(versions) == 1
            assert versions[0].version_number == 1
            assert versions[0].is_active is True

        engine.dispose()
    finally:
        tmpdir.cleanup()


__all__ = [
    "InvoiceTemplate",
    "TemplateVersion",
    "configure",
    "register_renderer",
    "render_invoice_template",
]


if __name__ == "__main__":
    _selftest()
    print("invoice_template selftest OK")
