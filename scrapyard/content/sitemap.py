"""
sitemap — Generate sitemap.xml + robots.txt.

### PART-META-JSON
{
  "name": "sitemap",
  "layer": "content",
  "purpose": "Generate sitemap.xml + robots.txt.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: build_robots(*, allow_all, sitemap_url); build_sitemap(urls).",
  "outputs": "Returns: build_robots -> str; build_sitemap -> str.",
  "files_created": [],
  "security_notes": "Renders HTML with all caller text escaped via html.escape (XSS-safe); any HTML 'slot' arguments are inserted verbatim and must be pre-escaped by the caller.",
  "ai_usage": "Import `build_robots` from `scrapyard.content.sitemap` and call it as shown in `example`; run `py -m scrapyard.content.sitemap` to see its offline selftest.",
  "example": "from scrapyard.content.sitemap import build_robots",
  "import_path": "scrapyard.content.sitemap"
}
### END-PART-META
"""
from __future__ import annotations
import html
STATUS = "core"
def build_robots(*, allow_all: bool = True, sitemap_url: str | None = None) -> str:
    """Generate a robots.txt body (companion to build_sitemap)."""
    lines = ["User-agent: *", "Allow: /" if allow_all else "Disallow: /"]
    if sitemap_url:
        lines.append(f"Sitemap: {sitemap_url}")
    return "\n".join(lines) + "\n"


def build_sitemap(urls: list[str]) -> str:
    items="".join(f"<url><loc>{html.escape(u)}</loc></url>" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+items+'</urlset>')


def _selftest() -> None:
    """Offline self-test: sitemap XML parses; robots.txt is well-formed."""
    import xml.etree.ElementTree as ET

    xml_doc = build_sitemap(["https://x.io/", "https://x.io/a?b=1&c=2"])
    root = ET.fromstring(xml_doc)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    locs = [e.text for e in root.iter(f"{ns}loc")]
    assert locs == ["https://x.io/", "https://x.io/a?b=1&c=2"]
    assert "&amp;" in xml_doc  # ampersand escaped

    assert ET.fromstring(build_sitemap([])).tag == f"{ns}urlset"

    robots = build_robots(sitemap_url="https://x.io/sitemap.xml")
    assert robots.splitlines() == ["User-agent: *", "Allow: /",
                                   "Sitemap: https://x.io/sitemap.xml"]
    assert "Disallow: /" in build_robots(allow_all=False)
    print("sitemap self-test passed")


if __name__ == "__main__":
    _selftest()
