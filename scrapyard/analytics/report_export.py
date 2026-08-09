"""
report_export - Pluggable report exporters (CSV/JSON/PDF) with destination validation and an export manager registry.

### PART-META-JSON
{
  "name": "report_export",
  "layer": "analytics",
  "purpose": "Pluggable report exporters (CSV/JSON/PDF) with destination validation and an export manager registry.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "register_exporter(cls); ReportExportManager().export(report_id, format, destination); validate_destination(path).",
  "outputs": "Report files written to validated destination paths.",
  "files_created": [],
  "security_notes": "Destination paths are validated to exist before writing, but callers pass arbitrary paths - do NOT pass user-controlled destinations without confining them to an export root, or this becomes an arbitrary-file-write primitive. Exported reports may contain analytics PII; treat output files as sensitive.",
  "ai_usage": "Import what you need from `scrapyard.analytics.report_export`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.analytics.report_export import ReportExportManager",
  "import_path": "scrapyard.analytics.report_export"
}
### END-PART-META
"""
from abc import ABC, abstractmethod
import os
import json
import logging
import tempfile

# Setup logger
logger = logging.getLogger(__name__)

class ReportExporter(ABC):
    @abstractmethod
    def export(self, report_id: str, destination: str) -> None:
        pass

def validate_destination(destination: str) -> bool:
    if not os.path.exists(os.path.dirname(destination)):
        raise ValueError(f"Destination directory does not exist: {destination}")
    return True

class CSVExporter(ReportExporter):
    def export(self, report_id: str, destination: str) -> None:
        logger.info(f"Exporting report {report_id} to {destination} in CSV format")
        # Simulate file writing
        with open(destination, 'w') as f:
            f.write("Header1,Header2\nData1,Data2")

class JSONExporter(ReportExporter):
    def export(self, report_id: str, destination: str) -> None:
        logger.info(f"Exporting report {report_id} to {destination} in JSON format")
        # Simulate file writing
        with open(destination, 'w') as f:
            json.dump({"report_id": report_id}, f)

class PDFExporter(ReportExporter):
    def export(self, report_id: str, destination: str) -> None:
        logger.info(f"Exporting report {report_id} to {destination} in PDF format")
        # Simulate file writing
        with open(destination, 'w') as f:
            f.write("PDF Content")

def register_exporter(exporter_class: type[ReportExporter]) -> None:
    logger.info(f"Registering exporter: {exporter_class}")
    # Simulate registration

class ReportExportManager:
    def __init__(self):
        self.exporters = {
            'csv': CSVExporter(),
            'json': JSONExporter(),
            'pdf': PDFExporter()
        }

    def export_report(self, report_id: str, destination: str) -> None:
        if not validate_destination(destination):
            raise ValueError("Invalid destination path")

        exporter_type = os.path.splitext(destination)[1][1:].lower()
        if exporter_type in self.exporters:
            self.exporters[exporter_type].export(report_id, destination)
        else:
            raise ValueError(f"Unsupported format: {exporter_type}")

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        manager = ReportExportManager()
        report_id = "12345"
        csv_dest = os.path.join(temp_dir, f"{report_id}.csv")
        json_dest = os.path.join(temp_dir, f"{report_id}.json")
        pdf_dest = os.path.join(temp_dir, f"{report_id}.pdf")

        # Test CSV export
        manager.export_report(report_id, csv_dest)
        assert os.path.exists(csv_dest), "CSV file not created"

        # Test JSON export
        manager.export_report(report_id, json_dest)
        with open(json_dest) as f:
            data = json.load(f)
            assert data['report_id'] == report_id, "JSON content incorrect"

        # Test PDF export
        manager.export_report(report_id, pdf_dest)
        assert os.path.exists(pdf_dest), "PDF file not created"

        # Test unsupported format
        try:
            manager.export_report(report_id, os.path.join(temp_dir, f"{report_id}.txt"))
        except ValueError as e:
            assert str(e) == "Unsupported format: txt", "Unexpected error message for unsupported format"

if __name__ == "__main__":
    _selftest()
