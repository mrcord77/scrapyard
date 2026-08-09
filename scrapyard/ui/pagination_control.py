"""
pagination_control — first/prev, numbered page window, next/last controls.

### PART-META-JSON
{
  "name": "pagination_control",
  "purpose": "Render page navigation for a paged listing: first/previous and next/last controls, the current page highlighted, a sibling window of nearby pages, ellipses for gaps, and disabled states at the ends. Integer inputs are coerced and clamped so out-of-range values render safely. Themed from the design tokens (surface/border/primary/muted/spacing).",
  "layer": "ui",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Keyword args: current_page (int), total_pages (int), base_url (href prefix a page number is appended to), siblings (ints on each side of current).",
  "outputs": "render_pagination(...) -> a <nav><ul>...</ul></nav> HTML string using var(--color-surface)/var(--color-border)/var(--color-primary)/var(--color-text-muted)/var(--space-*).",
  "files_created": [],
  "security_notes": "current_page/total_pages/siblings are forced through int() and clamped (never echoed as raw text), and base_url is escaped with html.escape (quote-escaped) before a page number is appended, so untrusted values cannot inject markup.",
  "ai_usage": "html = render_pagination(current_page=3, total_pages=20, base_url='/items?page='); the current page renders as non-link text with aria-current.",
  "example": "from scrapyard.ui.pagination_control import render_pagination; print(render_pagination(current_page=1, total_pages=5, base_url='?page='))",
  "import_path": "scrapyard.ui.pagination_control"
}
### END-PART-META
"""
from __future__ import annotations

import html
from typing import List, Optional

STATUS = "core"

_NAV = "font-family:var(--font-sans);font-size:var(--text-sm)"
_UL = ("list-style:none;display:flex;flex-wrap:wrap;align-items:center;"
       "gap:var(--space-1);margin:0;padding:0")
_CELL = ("display:inline-flex;align-items:center;justify-content:center;"
         "min-width:var(--space-6);padding:var(--space-2) var(--space-3);"
         "border:1px solid var(--color-border);border-radius:var(--radius-sm);"
         "text-decoration:none")
_LINK = f"{_CELL};background:var(--color-surface);color:var(--color-text)"
_CURRENT = f"{_CELL};background:var(--color-primary);color:#fff;font-weight:var(--weight-semibold)"
_DISABLED = (f"{_CELL};background:var(--color-surface);color:var(--color-text-muted);"
             "opacity:.5;cursor:not-allowed")
_ELLIPSIS = "padding:var(--space-2);color:var(--color-text-muted)"


def _int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _page_window(current: int, total: int, siblings: int) -> List[Optional[int]]:
    pages = {1, total, current}
    for p in range(current - siblings, current + siblings + 1):
        if 1 <= p <= total:
            pages.add(p)
    out: List[Optional[int]] = []
    prev = 0
    for p in sorted(pages):
        if p - prev > 1:
            out.append(None)  # ellipsis gap
        out.append(p)
        prev = p
    return out


def _control(label: str, page: Optional[int], base: str, enabled: bool) -> str:
    if enabled and page is not None:
        href = f"{base}{page}"
        return f'<li><a href="{href}" style="{_LINK}">{label}</a></li>'
    return f'<li><span aria-disabled="true" style="{_DISABLED}">{label}</span></li>'


def render_pagination(*, current_page: int, total_pages: int,
                      base_url: str = "?page=", siblings: int = 1) -> str:
    """Render page controls. Ints are coerced/clamped; base_url is escaped."""
    total = max(1, _int(total_pages, 1))
    current = min(max(1, _int(current_page, 1)), total)
    sib = max(0, _int(siblings, 1))
    base = html.escape(str(base_url), quote=True)

    items: List[str] = [
        _control("&laquo;", 1, base, current > 1),
        _control("&lsaquo;", current - 1, base, current > 1),
    ]
    for p in _page_window(current, total, sib):
        if p is None:
            items.append(f'<li><span style="{_ELLIPSIS}">&hellip;</span></li>')
        elif p == current:
            items.append(f'<li><span aria-current="page" style="{_CURRENT}">{p}</span></li>')
        else:
            items.append(f'<li><a href="{base}{p}" style="{_LINK}">{p}</a></li>')
    items.append(_control("&rsaquo;", current + 1, base, current < total))
    items.append(_control("&raquo;", total, base, current < total))

    return (f'<nav aria-label="Pagination" class="sy-pagination" style="{_NAV}">'
            f'<ul style="{_UL}">{"".join(items)}</ul></nav>')


def demo() -> str:
    """Self-contained sample: page 4 of 12 with a sibling window."""
    return render_pagination(current_page=4, total_pages=12, base_url="/parts?page=")


def _selftest() -> None:
    out = render_pagination(current_page=4, total_pages=12, base_url="/p?page=")
    assert out.startswith('<nav aria-label="Pagination"') and out.endswith("</nav>")
    assert "var(--color-primary)" in out and "var(--color-border)" in out
    # current page is non-link text with aria-current
    assert '<span aria-current="page"' in out and ">4<" in out
    # neighbours and ends are links; ellipsis present for the gap to 12
    assert "/p?page=3" in out and "/p?page=5" in out and "/p?page=12" in out
    assert "&hellip;" in out
    # first/prev disabled on page 1 (no page=0 link)
    first = render_pagination(current_page=1, total_pages=5, base_url="/p?page=")
    assert 'aria-disabled="true"' in first and "/p?page=0" not in first
    # out-of-range current clamps into [1,total]; garbage totals -> 1 page
    assert '>9<' in render_pagination(current_page=99, total_pages=9, base_url="/p?")
    assert render_pagination(current_page="x", total_pages="y", base_url="/p?").count("<li") >= 1
    # ADVERSARIAL: markup in base_url is escaped, not emitted live
    xss = render_pagination(current_page=1, total_pages=3,
                            base_url='/p?"><script>alert(1)</script>&x=')
    assert "<script>alert(1)</script>" not in xss and "&lt;script&gt;" in xss
    print("pagination_control selftest OK")


if __name__ == "__main__":
    _selftest()
