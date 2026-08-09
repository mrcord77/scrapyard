"""
sitemap_walker — Discovers and traverses URLs from real XML sitemaps (urlset and
sitemapindex, gzip-aware), fetching over HTTP or parsing from string/file, and feeds
each discovered URL to a crawler such as polite_crawler.

### PART-META-JSON
{
  "name": "sitemap_walker",
  "layer": "automation",
  "purpose": "Parses real XML sitemaps (urlset entries with loc/lastmod/changefreq/priority) and sitemap indexes (recursing into child sitemaps), handles gzip-compressed sitemaps, fetches via requests when given a URL, and walks discovered URLs through a caller-supplied crawler. Offline parse-from-string/file APIs allow use without network.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "requests"
  ],
  "inputs": "Sitemap URL, raw XML string/bytes (optionally gzipped), or local file path; a crawler object exposing crawl(url) for walking.",
  "outputs": "Lists of SitemapEntry records (loc, lastmod, changefreq, priority); Walker.walk returns the URLs it dispatched to the crawler.",
  "files_created": [],
  "security_notes": "Fetches attacker-controlled XML over the network: parsing uses xml.etree with default settings (DTD/entity expansion is not processed by ElementTree, mitigating billion-laughs), responses are size-capped (max_bytes, default 50 MB) and time-limited, and sitemap-index recursion is depth- and count-limited to stop sitemap bombs / infinite recursion. URLs extracted from sitemaps are untrusted input for whatever crawler you attach - the walker does not validate schemes beyond http/https filtering, so the crawler must apply its own robots/allowlist policy. No secrets handled.",
  "ai_usage": "parse_sitemap_string(xml) or parse_sitemap_file(path) offline; fetch_sitemap(url) online; Walker(crawler).walk(url_or_xml) to drive a crawler.",
  "example": "from scrapyard.automation.sitemap_walker import parse_sitemap_string; entries = parse_sitemap_string(xml_text)",
  "import_path": "scrapyard.automation.sitemap_walker"
}
### END-PART-META
"""

from __future__ import annotations

import gzip
import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Union

logger = logging.getLogger(__name__)

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # sitemap.org caps uncompressed sitemaps at 50MB
DEFAULT_TIMEOUT = 20.0
GZIP_MAGIC = b"\x1f\x8b"


@dataclass
class SitemapEntry:
    """One <url> entry from a urlset sitemap."""
    loc: str
    lastmod: Optional[str] = None
    changefreq: Optional[str] = None
    priority: Optional[float] = None


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(elem: ET.Element, name: str) -> Optional[str]:
    for child in elem:
        if _localname(child.tag) == name and child.text:
            return child.text.strip()
    return None


def _decompress_if_gzip(data: bytes, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
    if data[:2] == GZIP_MAGIC:
        data = gzip.decompress(data)
        if len(data) > max_bytes:
            raise ValueError(f"decompressed sitemap exceeds {max_bytes} bytes")
    return data


def parse_sitemap_string(xml_data: Union[str, bytes],
                         max_bytes: int = DEFAULT_MAX_BYTES) -> List[SitemapEntry]:
    """Parse a urlset sitemap from a string/bytes (gzip bytes accepted).

    For a sitemapindex document this returns the child sitemap locations as
    entries (use parse_sitemap_index or SitemapReader for recursion).
    """
    if isinstance(xml_data, bytes):
        xml_data = _decompress_if_gzip(xml_data, max_bytes)
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        raise ValueError(f"invalid sitemap XML: {exc}") from exc

    root_name = _localname(root.tag)
    entries: List[SitemapEntry] = []
    if root_name == "urlset":
        for url_elem in root:
            if _localname(url_elem.tag) != "url":
                continue
            loc = _child_text(url_elem, "loc")
            if not loc:
                continue
            prio_txt = _child_text(url_elem, "priority")
            try:
                priority = float(prio_txt) if prio_txt is not None else None
            except ValueError:
                priority = None
            entries.append(SitemapEntry(
                loc=loc,
                lastmod=_child_text(url_elem, "lastmod"),
                changefreq=_child_text(url_elem, "changefreq"),
                priority=priority,
            ))
    elif root_name == "sitemapindex":
        for sm_elem in root:
            if _localname(sm_elem.tag) != "sitemap":
                continue
            loc = _child_text(sm_elem, "loc")
            if loc:
                entries.append(SitemapEntry(loc=loc,
                                            lastmod=_child_text(sm_elem, "lastmod")))
    else:
        raise ValueError(f"unrecognized sitemap root element <{root_name}>; "
                         "expected <urlset> or <sitemapindex>")
    return entries


def is_sitemap_index(xml_data: Union[str, bytes]) -> bool:
    """True if the document's root element is <sitemapindex>."""
    if isinstance(xml_data, bytes):
        xml_data = _decompress_if_gzip(xml_data)
    try:
        return _localname(ET.fromstring(xml_data).tag) == "sitemapindex"
    except ET.ParseError:
        return False


def parse_sitemap_file(path: Union[str, os.PathLike],
                       max_bytes: int = DEFAULT_MAX_BYTES) -> List[SitemapEntry]:
    """Parse a sitemap from a local file (.xml or .xml.gz)."""
    with open(os.fspath(path), "rb") as fh:
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"sitemap file exceeds {max_bytes} bytes")
    return parse_sitemap_string(data, max_bytes)


def _fetch_bytes(url: str, timeout: float, max_bytes: int) -> bytes:
    import requests  # local import: offline parse paths never need it

    resp = requests.get(url, timeout=timeout, stream=True,
                        headers={"User-Agent": "scrapyard-sitemap-walker/1.0"})
    resp.raise_for_status()
    chunks: List[bytes] = []
    size = 0
    for chunk in resp.iter_content(chunk_size=65536):
        size += len(chunk)
        if size > max_bytes:
            raise ValueError(f"sitemap response exceeds {max_bytes} bytes: {url}")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_sitemap(url: str, *, timeout: float = DEFAULT_TIMEOUT,
                  max_bytes: int = DEFAULT_MAX_BYTES,
                  max_depth: int = 3, max_urls: int = 50000,
                  fetcher: Optional[Callable[[str], bytes]] = None) -> List[SitemapEntry]:
    """Fetch and fully parse a sitemap URL, recursing through sitemap indexes.

    `fetcher` overrides HTTP retrieval (url -> bytes) for testing or caching.
    Recursion is bounded by max_depth; total collected URLs by max_urls.
    """
    get = fetcher or (lambda u: _fetch_bytes(u, timeout, max_bytes))
    collected: List[SitemapEntry] = []
    seen_sitemaps = set()

    def _walk(u: str, depth: int) -> None:
        if len(collected) >= max_urls:
            return
        if u in seen_sitemaps:
            logger.warning("sitemap cycle detected at %s; skipping", u)
            return
        seen_sitemaps.add(u)
        data = _decompress_if_gzip(get(u), max_bytes)
        if is_sitemap_index(data):
            if depth >= max_depth:
                logger.warning("sitemap index depth limit (%d) reached at %s",
                               max_depth, u)
                return
            for child in parse_sitemap_string(data, max_bytes):
                _walk(child.loc, depth + 1)
        else:
            for entry in parse_sitemap_string(data, max_bytes):
                if len(collected) >= max_urls:
                    return
                collected.append(entry)

    _walk(url, 0)
    return collected


class SitemapReader:
    """Reads one sitemap source (URL, XML string/bytes, or file path)."""

    def __init__(self, source: str, *, timeout: float = DEFAULT_TIMEOUT,
                 max_bytes: int = DEFAULT_MAX_BYTES,
                 fetcher: Optional[Callable[[str], bytes]] = None) -> None:
        self.source = source
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.fetcher = fetcher
        self.entries: List[SitemapEntry] = []

    def parse(self) -> List[str]:
        """Parse the source (recursing through indexes when fetchable) and return URL strings."""
        src = self.source
        if isinstance(src, str) and src.lower().startswith(("http://", "https://")):
            self.entries = fetch_sitemap(src, timeout=self.timeout,
                                         max_bytes=self.max_bytes,
                                         fetcher=self.fetcher)
        elif isinstance(src, str) and os.path.isfile(src):
            self.entries = parse_sitemap_file(src, self.max_bytes)
        else:
            self.entries = parse_sitemap_string(src, self.max_bytes)
        return [e.loc for e in self.entries]


class Walker:
    """Feeds every URL discovered in a sitemap to crawler.crawl(url)."""

    def __init__(self, crawler: Any) -> None:
        if not hasattr(crawler, "crawl"):
            raise ValueError("crawler must expose a crawl(url) method")
        self.crawler = crawler

    def walk(self, sitemap_source: str, **reader_kwargs: Any) -> List[str]:
        reader = SitemapReader(sitemap_source, **reader_kwargs)
        urls = reader.parse()
        for url in urls:
            logger.info("dispatching crawler to %s", url)
            self.crawler.crawl(url)
        return urls


def _selftest() -> None:
    urlset_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url><loc>http://example.com/page1</loc><lastmod>2026-01-01</lastmod>
       <changefreq>daily</changefreq><priority>0.8</priority></url>
  <url><loc>http://example.com/page2</loc></url>
  <url><priority>0.5</priority></url>
</urlset>"""

    # 1. Real urlset parsing with all optional fields
    entries = parse_sitemap_string(urlset_xml)
    assert len(entries) == 2, entries  # entry without <loc> dropped
    assert entries[0].loc == "http://example.com/page1"
    assert entries[0].lastmod == "2026-01-01"
    assert entries[0].changefreq == "daily"
    assert entries[0].priority == 0.8
    assert entries[1].priority is None

    # 2. Un-namespaced sitemaps still parse
    plain = "<urlset><url><loc>http://a/x</loc></url></urlset>"
    assert parse_sitemap_string(plain)[0].loc == "http://a/x"

    # 3. Gzip support (bytes path) + file path
    import tempfile
    gz = gzip.compress(urlset_xml.encode())
    assert len(parse_sitemap_string(gz)) == 2
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        p = os.path.join(tmp, "sitemap.xml.gz")
        with open(p, "wb") as fh:
            fh.write(gz)
        assert len(parse_sitemap_file(p)) == 2

    # 4. sitemapindex recursion via injected fetcher (no network)
    index_xml = f"""<sitemapindex xmlns="{SITEMAP_NS}">
      <sitemap><loc>http://example.com/s1.xml</loc></sitemap>
      <sitemap><loc>http://example.com/s2.xml.gz</loc></sitemap>
    </sitemapindex>"""
    child1 = f"<urlset xmlns='{SITEMAP_NS}'><url><loc>http://example.com/a</loc></url></urlset>"
    child2 = f"<urlset xmlns='{SITEMAP_NS}'><url><loc>http://example.com/b</loc></url></urlset>"
    store = {
        "http://example.com/index.xml": index_xml.encode(),
        "http://example.com/s1.xml": child1.encode(),
        "http://example.com/s2.xml.gz": gzip.compress(child2.encode()),
    }
    entries = fetch_sitemap("http://example.com/index.xml", fetcher=store.__getitem__)
    assert [e.loc for e in entries] == ["http://example.com/a", "http://example.com/b"]

    # 5. Cycle safety: an index pointing at itself terminates
    cyc = f"<sitemapindex xmlns='{SITEMAP_NS}'><sitemap><loc>http://c/i.xml</loc></sitemap></sitemapindex>"
    got = fetch_sitemap("http://c/i.xml", fetcher={"http://c/i.xml": cyc.encode()}.__getitem__)
    assert got == []

    # 6. Invalid XML / wrong root are honest errors
    for bad in ("<not-xml", "<rss></rss>"):
        try:
            parse_sitemap_string(bad)
            raise AssertionError(f"should reject {bad!r}")
        except ValueError:
            pass

    # 7. Walker drives a crawler over discovered URLs
    crawled: List[str] = []

    class _Crawler:
        def crawl(self, url: str) -> None:
            crawled.append(url)

    walked = Walker(_Crawler()).walk(urlset_xml)
    assert walked == crawled == ["http://example.com/page1", "http://example.com/page2"]

    print("sitemap_walker selftest: all tests passed")


if __name__ == "__main__":
    _selftest()
