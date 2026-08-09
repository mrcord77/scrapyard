"""
estimation_exporter — ** Exports estimation data in multiple formats for use in sales and pricing workflows. Designed to be reusable across products, it ensures consistent data serialization and reporting.

### PART-META-JSON
{
  "name": "estimation_exporter",
  "layer": "sales",
  "purpose": "Exports estimation data in multiple formats for use in sales and pricing workflows. Designed to be reusable across products, it ensures consistent data serialization and reporting.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: export_to_excel(estimate_data); generate_pdf_report(estimate_data); serialize_estimate(estimate_data).",
  "outputs": "Returns: export_to_excel -> BytesIO; generate_pdf_report -> BytesIO; serialize_estimate -> str.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.sales.estimation_exporter`.",
  "example": "from scrapyard.sales.estimation_exporter import *",
  "import_path": "scrapyard.sales.estimation_exporter"
}
### END-PART-META
"""
from typing import List, Dict
import json
from io import BytesIO
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

try:
    import pandas as pd
except ImportError:
    pd = None
    logger.warning("pandas not available for Excel export")


def export_to_excel(estimate_data: List[Dict]) -> BytesIO:
    """Export estimate data to Excel format."""
    if pd is None:
        raise ImportError("pandas is required for Excel export")
    df = pd.DataFrame(estimate_data)
    excel_file = BytesIO()
    df.to_excel(excel_file, index=False, engine='openpyxl')
    excel_file.seek(0)
    return excel_file


def _build_minimal_pdf(estimate_data: List[Dict]) -> bytes:
    """Build minimal PDF bytes without external libraries."""
    objects = []
    
    # Object 1: Catalog
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj"
    objects.append(obj1)
    
    # Object 2: Pages
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj"
    objects.append(obj2)
    
    # Object 3: Page
    obj3 = b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> /Contents 4 0 R >>\nendobj"
    objects.append(obj3)
    
    # Build content stream
    lines = []
    if not estimate_data:
        lines.append("No estimate data available.")
    else:
        for item in estimate_data:
            for key, value in item.items():
                lines.append(f"{key}: {value}")
    
    y_pos = 700
    stream_ops = ["BT", "/F1 12 Tf"]
    for line in lines:
        # PDF string escaping for parentheses and backslash
        safe_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_ops.append(f"100 {y_pos} Td")
        stream_ops.append(f"({safe_line}) Tj")
        y_pos -= 15
    stream_ops.append("ET")
    
    stream_data = "\n".join(stream_ops).encode('latin-1')
    obj4 = f"4 0 obj\n<< /Length {len(stream_data)} >>\nstream\n".encode() + stream_data + b"\nendstream\nendobj"
    objects.append(obj4)
    
    # Assemble PDF with proper xref offsets
    pdf_parts = [b"%PDF-1.4"]
    offsets = []
    
    for obj in objects:
        offsets.append(sum(len(p) + 1 for p in pdf_parts))
        pdf_parts.append(obj)
    
    xref_start = sum(len(p) + 1 for p in pdf_parts)
    
    xref_lines = [b"xref", f"0 {len(objects) + 1}".encode()]
    xref_lines.append(b"0000000000 65535 f ")
    for offset in offsets:
        xref_lines.append(f"{offset:010d} 00000 n ".encode())
    
    pdf_parts.extend(xref_lines)
    pdf_parts.append(b"trailer")
    pdf_parts.append(f"<< /Size {len(objects) + 1} /Root 1 0 R >>".encode())
    pdf_parts.append(b"startxref")
    pdf_parts.append(str(xref_start).encode())
    pdf_parts.append(b"%%EOF")
    
    return b"\n".join(pdf_parts)


def generate_pdf_report(estimate_data: List[Dict]) -> BytesIO:
    """Generate PDF report from estimate data."""
    pdf_bytes = _build_minimal_pdf(estimate_data)
    pdf_buffer = BytesIO(pdf_bytes)
    pdf_buffer.seek(0)
    return pdf_buffer


def serialize_estimate(estimate_data: List[Dict]) -> str:
    """Serialize estimate data to JSON string."""
    return json.dumps(estimate_data, indent=4)


def _selftest():
    """Self-test function to verify module functionality."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        test_data = [
            {"Part": "Steel Beam", "Quantity": 10, "Price": 500.0},
            {"Part": "Concrete Block", "Quantity": 20, "Price": 75.0}
        ]
        
        # Test export_to_excel with valid data
        excel_file = export_to_excel(test_data)
        excel_content = excel_file.getvalue()
        assert excel_content, "Export to Excel failed - empty content"
        
        # Verify Excel is valid by writing and reading back
        excel_path = os.path.join(temp_dir, "test.xlsx")
        with open(excel_path, "wb") as f:
            f.write(excel_content)
        df_read = pd.read_excel(excel_path)
        assert len(df_read) == 2, "Excel data row count mismatch"
        assert "Part" in df_read.columns, "Excel missing Part column"
        
        # Test export_to_excel with empty data
        empty_excel = export_to_excel([])
        empty_excel_content = empty_excel.getvalue()
        assert empty_excel_content, "Export to Excel with empty data failed - empty content"
        empty_excel_path = os.path.join(temp_dir, "empty.xlsx")
        with open(empty_excel_path, "wb") as f:
            f.write(empty_excel_content)
        empty_df = pd.read_excel(empty_excel_path)
        assert len(empty_df) == 0, "Empty Excel should have 0 rows"
        
        # Test generate_pdf_report with valid data
        pdf_file = generate_pdf_report(test_data)
        pdf_content = pdf_file.getvalue()
        assert pdf_content, "Generate PDF Report failed - empty content"
        assert pdf_content.startswith(b'%PDF'), "Generated file is not a valid PDF"
        
        pdf_path = os.path.join(temp_dir, "test.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_content)
        
        # Test generate_pdf_report with empty data
        empty_pdf = generate_pdf_report([])
        empty_pdf_content = empty_pdf.getvalue()
        assert empty_pdf_content, "Generate PDF Report with empty data failed - empty content"
        assert empty_pdf_content.startswith(b'%PDF'), "Empty PDF is not valid"
        
        empty_pdf_path = os.path.join(temp_dir, "empty.pdf")
        with open(empty_pdf_path, "wb") as f:
            f.write(empty_pdf_content)
        
        # Test serialize_estimate with valid data
        serialized = serialize_estimate(test_data)
        assert serialized, "Serialize Estimate failed - empty string"
        parsed = json.loads(serialized)
        assert isinstance(parsed, list) and len(parsed) == 2, "JSON deserialization failed"
        
        # Test serialize_estimate with empty data
        empty_serialized = serialize_estimate([])
        assert empty_serialized == "[]", f"Empty serialization failed, got: {empty_serialized}"
        assert json.loads(empty_serialized) == [], "Empty JSON parsing failed"
        
        print("All tests passed!")


if __name__ == "__main__":
    _selftest()
