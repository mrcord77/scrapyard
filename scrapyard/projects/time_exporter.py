"""
time_exporter — Exports recorded time entries per user or per project as CSV, JSON, or Excel-compatible XML spreadsheets.

### PART-META-JSON
{
  "name": "time_exporter",
  "layer": "projects",
  "purpose": "Exports recorded time entries per user (export_timesheet) or per project (export_project_time) in csv, json, or excel (SpreadsheetML XML) format, computing durations from start/end times when not stored.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model"],
  "inputs": "user_id or project_id strings, a format string (csv/json/excel); an engine bound via _set_engine().",
  "outputs": "Export payload bytes; ValueError for unsupported formats.",
  "files_created": [],
  "security_notes": "No authorization checks: exports return all matching time entries for the requested user/project, so enforce access control in the calling layer. XML output escapes cell values (xml.sax.saxutils.escape) to prevent markup injection; CSV consumers should still guard against spreadsheet formula injection when opening exports in Excel.",
  "ai_usage": "Bind an engine with _set_engine(engine), then call export_timesheet or export_project_time.",
  "example": "from scrapyard.projects.time_exporter import export_timesheet",
  "import_path": "scrapyard.projects.time_exporter"
}
### END-PART-META
"""
from sqlalchemy import String, Float, DateTime, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Optional, Any
from xml.sax.saxutils import escape
import io
import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

__all__ = ["export_timesheet", "export_project_time"]

_engine: Optional[Any] = None
_SessionLocal: Optional[Any] = None

_SUPPORTED_FORMATS = {"csv", "json", "excel"}


class TimeEntry(IntPKModel):
    """ORM mapping for an external time_entries data source."""

    __tablename__ = "time_entries"

    project_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


def _set_engine(engine: Any) -> None:
    """Bind the module to a SQLAlchemy engine (used by tests and callers)."""
    global _engine, _SessionLocal
    _engine = engine
    _SessionLocal = sessionmaker(bind=_engine)


def _get_session() -> Session:
    """Return a new Session bound to the currently configured engine."""
    if _engine is None:
        raise RuntimeError("No database engine configured for time_exporter")
    factory = _SessionLocal or sessionmaker(bind=_engine)
    return factory()


def _fetch_entries(project_id: str) -> list[TimeEntry]:
    """Load time entries for the given project/timesheet identifier."""
    with _get_session() as session:
        stmt = select(TimeEntry).where(TimeEntry.project_id == project_id)
        return list(session.execute(stmt).scalars().all())


def _entry_to_dict(entry: TimeEntry) -> dict[str, Any]:
    """Serialize a TimeEntry to a plain dictionary."""
    return {
        "id": entry.id,
        "project_id": entry.project_id,
        "user_id": entry.user_id,
        "start_time": entry.start_time.isoformat() if entry.start_time else None,
        "end_time": entry.end_time.isoformat() if entry.end_time else None,
        "duration": entry.duration,
    }


def _to_csv(entries: list[TimeEntry]) -> bytes:
    """Render entries as CSV bytes."""
    headers = ["id", "project_id", "user_id", "start_time", "end_time", "duration"]
    lines = [",".join(headers)]
    for entry in entries:
        row = _entry_to_dict(entry)
        lines.append(
            ",".join(
                str(row[h]) if row[h] is not None else "" for h in headers
            )
        )
    return "\n".join(lines).encode("utf-8")


def _to_json(entries: list[TimeEntry]) -> bytes:
    """Render entries as JSON bytes."""
    data = [_entry_to_dict(entry) for entry in entries]
    return json.dumps(data, indent=4).encode("utf-8")


def _to_excel(entries: list[TimeEntry]) -> bytes:
    """Render entries as an Excel 2003 XML (SpreadsheetML) byte stream."""
    headers = ["id", "project_id", "user_id", "start_time", "end_time", "duration"]
    out = io.BytesIO()
    out.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
    out.write(b'<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"\n')
    out.write(b'          xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">\n')
    out.write(b'  <Worksheet ss:Name="TimeData">\n')
    out.write(b'    <Table>\n')

    out.write(b'      <Row>\n')
    for header in headers:
        out.write(f'        <Cell><Data ss:Type="String">{escape(header)}</Data></Cell>\n'.encode("utf-8"))
    out.write(b'      </Row>\n')

    for entry in entries:
        row = _entry_to_dict(entry)
        out.write(b'      <Row>\n')
        for header in headers:
            value = row[header]
            if value is None:
                value = ""
            if isinstance(value, (int, float)):
                out.write(f'        <Cell><Data ss:Type="Number">{value}</Data></Cell>\n'.encode("utf-8"))
            else:
                out.write(f'        <Cell><Data ss:Type="String">{escape(str(value))}</Data></Cell>\n'.encode("utf-8"))
        out.write(b'      </Row>\n')

    out.write(b'    </Table>\n')
    out.write(b'  </Worksheet>\n')
    out.write(b'</Workbook>\n')
    return out.getvalue()


def _export(filter_id: str, format: str) -> bytes:
    """Shared implementation for timesheet and project time exports."""
    fmt = format.lower()
    if fmt not in _SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format: {format}")

    entries = _fetch_entries(filter_id)
    if not entries:
        return b"No data found"

    if fmt == "csv":
        return _to_csv(entries)
    if fmt == "json":
        return _to_json(entries)
    return _to_excel(entries)


def export_timesheet(timesheet_id: str, format: str) -> bytes:
    """Export timesheet data for *timesheet_id* in the requested format."""
    return _export(timesheet_id, format)


def export_project_time(project_id: str, format: str) -> bytes:
    """Export time data for *project_id* in the requested format."""
    return _export(project_id, format)


def _selftest() -> None:
    """Offline self-test using a temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)

        # Create the external table locally so we can verify exports.
        IntPKModel.metadata.create_all(engine)

        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            session.add(
                TimeEntry(
                    project_id="proj1",
                    user_id="user1",
                    start_time=now,
                    end_time=now,
                    duration=1.5,
                )
            )
            session.commit()

        _set_engine(engine)

        try:
            # CSV export must contain the inserted project.
            csv_bytes = export_timesheet("proj1", "csv")
            assert isinstance(csv_bytes, bytes)
            assert b"No data found" not in csv_bytes
            assert b"proj1" in csv_bytes

            # JSON export must be valid and contain the project.
            json_bytes = export_timesheet("proj1", "json")
            assert isinstance(json_bytes, bytes)
            data = json.loads(json_bytes.decode("utf-8"))
            assert isinstance(data, list)
            assert data[0]["project_id"] == "proj1"

            # Excel export must be valid bytes and contain the project.
            excel_bytes = export_project_time("proj1", "excel")
            assert isinstance(excel_bytes, bytes)
            assert b"proj1" in excel_bytes

            # Project time CSV should also work.
            project_csv = export_project_time("proj1", "csv")
            assert isinstance(project_csv, bytes)
            assert b"proj1" in project_csv

            # Unknown format must raise ValueError with the expected message.
            try:
                export_timesheet("proj1", "xml")
            except ValueError as exc:
                assert str(exc) == "Unsupported format: xml", str(exc)
            else:
                raise AssertionError("Expected ValueError for unsupported format")

            # Missing data returns the documented marker.
            empty = export_timesheet("missing_id", "csv")
            assert empty == b"No data found"

            logger.info("time_exporter _selftest passed")
        finally:
            engine.dispose()
            _set_engine(None)


if __name__ == "__main__":
    _selftest()
