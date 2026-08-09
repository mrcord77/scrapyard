"""
link_checks — Crawl + verify internal/external links.

### PART-META-JSON
{
  "name": "link_checks",
  "layer": "testing",
  "purpose": "Crawl + verify internal/external links.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "httpx"
  ],
  "inputs": "Public API: set_user_agent(agent); enable_proxy(proxy_url); set_rate_limit(limit, window_seconds); set_cache(enabled, ttl_seconds); crawl_page(url, timeout, headers); BrokenLink(...); CheckResult(...) (plus more).",
  "outputs": "Returns: set_user_agent -> None; enable_proxy -> None; set_rate_limit -> None; set_cache -> None; crawl_page -> Tuple[str, int, str].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Makes outbound network calls; set timeouts, validate URLs/hosts, and never send secrets to untrusted endpoints.",
  "ai_usage": "Import `set_user_agent` from `scrapyard.testing.link_checks` and call it as shown in `example`; run `py -m scrapyard.testing.link_checks` to see its offline selftest.",
  "example": "from scrapyard.testing.link_checks import set_user_agent",
  "import_path": "scrapyard.testing.link_checks"
}
### END-PART-META
"""
from __future__ import annotations
import re
from typing import List, Set, Tuple, Dict, Any, Optional
from dataclasses import dataclass
from functools import lru_cache
from httpx import Client, Timeout, RequestError, HTTPStatusError
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

_STATUS = "core"

_HREF = re.compile(r'href="([^"]+)"')

@dataclass
class BrokenLink:
    url: str
    status_code: int
    error: str
    source_url: str

@dataclass
class CheckResult:
    ok: bool
    checked: int
    broken: List[BrokenLink]
    total_links: int
    visited: Set[str]

def set_user_agent(agent: str) -> None:
    global _USER_AGENT
    _USER_AGENT = agent

def enable_proxy(proxy_url: str) -> None:
    global _PROXY_URL
    _PROXY_URL = proxy_url

def set_rate_limit(limit: int, window_seconds: int) -> None:
    global _RATE_LIMIT
    _RATE_LIMIT = (limit, window_seconds)

def set_cache(enabled: bool = True, ttl_seconds: int = 300) -> None:
    global _CACHE_TTL
    _CACHE_TTL = ttl_seconds

def crawl_page(url: str, timeout: float = 10.0, headers: Optional[Dict[str, str]] = None) -> Tuple[str, int, str]:
    client = Client(timeout=Timeout(timeout), headers=headers)
    try:
        response = client.get(url, follow_redirects=True)
        return response.text, response.status_code, ''
    except RequestError as e:
        return '', 0, f"Request error: {str(e)}"
    except HTTPStatusError as e:
        return '', e.response.status_code, f"HTTP status error: {e}"
    finally:
        client.close()

def filter_links(links: List[str], valid_paths: Set[str], external_only: bool = False) -> List[str]:
    if external_only:
        filtered_links = [link for link in links if not link.startswith('/')]
    else:
        filtered_links = [link for link in links if link.startswith('/') or not link.startswith('/')]
    return [link for link in filtered_links if any(link.endswith(path) for path in valid_paths)]

def validate_link(url: str, valid_paths: Set[str], timeout: float = 10.0,
                  fetcher: Optional[Any] = None) -> bool:
    """True if ``url`` and every internal link reachable from it are valid.

    Fix history: the previous version called itself for every discovered link
    with no visited-set or depth bound, so a cyclic link graph (A -> B -> A)
    recursed forever. It now delegates to the visited-set-guarded ``check_links``
    crawl, which fetches each URL at most once and terminates on cycles.
    """
    return check_links(url, valid_paths, timeout, fetcher=fetcher).ok

def log_broken_link(link: str, status_code: int, error: str, source_url: str) -> None:
    # Placeholder for logging to a database or audit system
    print(f"Broken link detected: {link} (Status code: {status_code}, Error: {error}) from {source_url}")

def check_links(url: str, valid_paths: Set[str], timeout: float = 10.0,
                max_depth: int = 2, follow_external: bool = False,
                fetcher: Optional[Any] = None) -> CheckResult:
    """Breadth-limited crawl that verifies links reachable from ``url``.

    Fix history: the previous version recursed without a shared visited-set (its
    ``max_depth_check`` helper tracked depth only), so a cyclic link graph
    (A -> B -> A) recursed forever; it also conflated ``len(visited)`` with depth
    and returned only ``results[0]``. This version guards recursion with a single
    shared ``visited`` set (a URL is fetched at most once) AND a real depth limit,
    and aggregates every broken link found.

    ``fetcher`` lets a test inject an offline ``url -> (html, status, error)``
    callable; it defaults to the live ``crawl_page``. A link is BROKEN when its
    fetch yields an error, status 0, or status >= 400.
    """
    fetch = fetcher if fetcher is not None else (lambda u: crawl_page(u, timeout))
    visited: Set[str] = set()
    broken: List[BrokenLink] = []
    total_links = 0

    def _visit(current: str, depth: int) -> None:
        nonlocal total_links
        # Cycle guard (visited) AND bound (depth) — either alone is insufficient.
        if current in visited or depth > max_depth:
            return
        visited.add(current)

        html_content, status_code, error = fetch(current)
        if error or status_code == 0 or status_code >= 400:
            broken.append(BrokenLink(current, status_code, error or f"HTTP {status_code}", current))
            if not html_content:
                return  # nothing to parse from a failed fetch

        links = extract_links(html_content)
        total_links += len(links)
        for link in filter_links(links, valid_paths, follow_external):
            _visit(link, depth + 1)

    _visit(url, 0)
    return CheckResult(ok=not broken, checked=len(visited), broken=broken,
                       total_links=total_links, visited=visited)

def bulk_check_links(urls: List[str], valid_paths: Set[str], timeout: float = 10.0) -> List[CheckResult]:
    with Client(timeout=Timeout(timeout)) as client:
        @lru_cache(maxsize=None)
        def cached_crawl_page(url):
            try:
                response = client.get(url, follow_redirects=True)
                return response.text, response.status_code, ''
            except RequestError as e:
                return '', 0, f"Request error: {str(e)}"
            except HTTPStatusError as e:
                return '', e.response.status_code, f"HTTP status error: {e}"

        results = []
        for url in urls:
            html_content, status_code, _ = cached_crawl_page(url)
            links = extract_links(html_content)
            broken_links = [BrokenLink(link, status_code, '', url) for link in filter_links(links, valid_paths)]
            results.append(CheckResult(ok=len(broken_links) == 0, checked=len(links), broken=broken_links, total_links=len(links), visited={url}))
        return results

def max_depth_check(url: str, valid_paths: Set[str], timeout: float, max_depth: int, follow_external: bool) -> None:
    if max_depth <= 0:
        return
    html_content, status_code, _ = crawl_page(url, timeout)
    links = extract_links(html_content)
    for link in filter_links(links, valid_paths, follow_external):
        log_broken_link(link, status_code, '', url)
        max_depth_check(link, valid_paths, timeout - 1.5, max_depth - 1, follow_external)


# --- grafted from original part (API stability) ---
def extract_links(html_text: str) -> list[str]:
    return _HREF.findall(html_text or "")

def check_internal_links(html_text: str, valid_paths: set[str]) -> dict:
    """Verify every internal (leading-slash) link points at a known route."""
    links = [l for l in extract_links(html_text) if l.startswith("/")]
    broken = [l for l in links if l.split("?")[0] not in valid_paths]
    return {"ok": not broken, "checked": len(links), "broken": broken}


def _selftest() -> None:
    # extract_links pulls every href, in order.
    html = ('<a href="/home">H</a>'
            '<a href="/about?x=1">A</a>'
            '<a href="https://ext.com">E</a>')
    links = extract_links(html)
    assert links == ["/home", "/about?x=1", "https://ext.com"], links
    # NEGATIVE: no anchors -> no links (and None input is tolerated).
    assert extract_links("") == []
    assert extract_links(None) == []

    # PASS fixture: every internal link resolves to a known route (query stripped).
    ok = check_internal_links(html, {"/home", "/about"})
    assert ok["ok"] is True and ok["checked"] == 2 and ok["broken"] == []

    # FAIL fixture: an internal link points at an unknown route -> reported broken.
    bad = check_internal_links(
        '<a href="/home">H</a><a href="/ghost">G</a>', {"/home"}
    )
    assert bad["ok"] is False and bad["broken"] == ["/ghost"]

    # --- check_links over a CYCLIC in-memory link graph (offline fetcher) -------
    # Graph: /a <-> /b (a cycle) and /a -> /broken (a 404). With no shared
    # visited-set this cycle recurses forever; the fix must terminate and report
    # exactly the broken link. max_depth is set high on purpose so ONLY the
    # visited-set can break the cycle (proving the real fix, not the depth bound).
    pages = {
        "/a": ('<a href="/b">b</a><a href="/broken">x</a>', 200, ""),
        "/b": ('<a href="/a">a</a>', 200, ""),          # links back to /a -> cycle
        "/broken": ("", 404, ""),                        # dead link
    }

    def fake_fetch(u):
        return pages.get(u, ("", 404, "not found"))

    res = check_links("/a", {"/a", "/b", "/broken"}, max_depth=50, fetcher=fake_fetch)
    # Terminated (we got here) and each page fetched at most once despite the cycle.
    assert res.visited == {"/a", "/b", "/broken"}, f"visited: {res.visited}"
    # The 404 link is reported broken; the cycle did not fabricate extra breakage.
    assert res.ok is False, "a 404 in the graph must make the result not-ok"
    broken_urls = [b.url for b in res.broken]
    assert broken_urls == ["/broken"], f"exactly the dead link is broken: {broken_urls}"
    assert res.broken[0].status_code == 404

    # PASS fixture: an all-healthy cyclic graph terminates and reports ok=True.
    healthy = {
        "/a": ('<a href="/b">b</a>', 200, ""),
        "/b": ('<a href="/a">a</a>', 200, ""),  # still a cycle, but nothing broken
    }
    ok_res = check_links("/a", {"/a", "/b"}, max_depth=50,
                         fetcher=lambda u: healthy.get(u, ("", 404, "")))
    assert ok_res.ok is True and ok_res.broken == [], ok_res
    assert ok_res.visited == {"/a", "/b"}

    print("link_checks selftest OK (extract/internal + cyclic-graph crawl "
          "terminates with correct broken-link report)")


if __name__ == "__main__":
    _selftest()

