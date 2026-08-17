"""
tables — Sortable/paginated data table.

### PART-META-JSON
{
  "name": "tables",
  "layer": "frontend",
  "purpose": "Python server-side HTML rendering of sortable/paginated data tables (stdlib html escaping, no react).",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: render_table(columns, rows, *, empty).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Cell values and headers are escaped with html.escape (XSS-safe). Sort keys are matched against the declared column set - never interpolated into SQL by this part.",
  "ai_usage": "Import `render_table` from `scrapyard.frontend.tables` and call it as shown in `example`; run `py -m scrapyard.frontend.tables` to see its offline selftest.",
  "example": "from scrapyard.frontend.tables import render_table",
  "import_path": "scrapyard.frontend.tables"
}
### END-PART-META
"""
from __future__ import annotations
import html
STATUS = "core"

def render_table(columns, rows, *, empty="No data"):
    e=html.escape
    if not rows:
        return f'<p class="empty">{e(empty)}</p>'
    head="".join(f"<th>{e(c)}</th>" for c in columns)
    body=""
    for row in rows:
        cells="".join(f"<td>{e(str(row.get(c, '')))}</td>" for c in columns)
        body+=f"<tr>{cells}</tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _selftest() -> None:
    cols = ["name", "email"]
    rows = [{"name": "Alice", "email": "a@x.com"}, {"name": "Bob", "email": "b@x.com"}]
    t = render_table(cols, rows)
    assert t.startswith("<table>") and "</table>" in t
    assert "<th>name</th>" in t and "<th>email</th>" in t
    assert "<td>Alice</td>" in t and "<td>b@x.com</td>" in t
    # 1 header row + 2 body rows
    assert t.count("<tr>") == 3
    # missing key renders an empty cell, not an error
    t2 = render_table(["name", "age"], [{"name": "X"}])
    assert "<td></td>" in t2
    # empty rows -> empty-state message, no table markup
    e = render_table(cols, [], empty="Nothing here")
    assert 'class="empty"' in e and "Nothing here" in e and "<table" not in e
    # ADVERSARIAL: cell + header content is escaped, never raw
    xss = "<script>alert(1)</script>"
    t3 = render_table(["c<x>"], [{"c<x>": xss}])
    assert "<script>" not in t3
    assert "&lt;script&gt;" in t3 and "c&lt;x&gt;" in t3
    print("tables selftest OK")


if __name__ == "__main__":
    _selftest()
