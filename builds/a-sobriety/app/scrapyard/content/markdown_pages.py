"""
markdown_pages — Render markdown pages with front-matter.

### PART-META-JSON
{
  "name": "markdown_pages",
  "layer": "content",
  "purpose": "Render markdown pages with front-matter.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "markdown"
  ],
  "inputs": "Public API: render_markdown_with_frontmatter(md); render_markdown_with_frontmatter_and_validation(md, schema); render_markdown_from_file(path); render_markdown_from_string_with_config(md, config); bulk_render_markdown(pages); MarkdownConfig(...); InvalidFrontmatterError(...); MarkdownParseError(...) (plus more).",
  "outputs": "Returns: render_markdown_with_frontmatter -> dict[str, Any]; render_markdown_with_frontmatter_and_validation -> dict[str, Any]; render_markdown_from_file -> dict[str, Any]; render_markdown_from_string_with_config -> str; bulk_render_markdown -> List[dict[str, Any]].",
  "files_created": [],
  "security_notes": "Renders HTML with all caller text escaped via html.escape (XSS-safe); any HTML 'slot' arguments are inserted verbatim and must be pre-escaped by the caller. Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import `render_markdown_with_frontmatter` from `scrapyard.content.markdown_pages` and call it as shown in `example`; run `py -m scrapyard.content.markdown_pages` to see its offline selftest.",
  "example": "from scrapyard.content.markdown_pages import render_markdown_with_frontmatter",
  "import_path": "scrapyard.content.markdown_pages"
}
### END-PART-META
"""
from __future__ import annotations
import re
import html
import yaml
from typing import Any, Type, Callable, List
from pydantic import BaseModel, ValidationError


STATUS = "core"

class MarkdownConfig(BaseModel):
    escape_html: bool = True
    allow_links: bool = True
    max_heading_level: int = 3
    render_policy: str = "safe"

class InvalidFrontmatterError(Exception):
    pass

class MarkdownParseError(Exception):
    pass

class ConfigNotFoundError(Exception):
    pass

class HookRegistrationError(Exception):
    pass

_RENDER_HOOKS = []

def _render_markdown(md: str, config: MarkdownConfig) -> str:
    out = []
    for block in (md or "").split("\n\n"):
        t = block.strip()
        if config.escape_html:
            t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"\*(.+?)\*", r"<em>\1</em>", t)
        t = re.sub(r"\[(.+?)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', t)
        m = re.match(r"(#{1,3})\s+(.*)", t)
        if m:
            lvl = len(m.group(1))
            if lvl > config.max_heading_level:
                continue
            out.append(f"<h{lvl}>{m.group(2)}</h{lvl}>")
        elif t:
            out.append(f"<p>{t}</p>")
    return "\n".join(out)

def render_markdown_with_frontmatter(md: str) -> dict[str, Any]:
    try:
        frontmatter, content = md.split("\n---\n", 1)
        data = yaml.safe_load(frontmatter)
        html_content = _render_markdown(content.strip(), get_render_config())
        html_content = _default_template.format(content=html_content)
        result = {"frontmatter": data, "html": html_content}
    except (yaml.YAMLError, ValueError) as e:
        raise InvalidFrontmatterError("Invalid YAML front-matter") from e
    for hook in _RENDER_HOOKS:
        try:
            hook(md, result)
        except Exception:
            pass  # observer hooks never break rendering
    return result

def render_markdown_with_frontmatter_and_validation(md: str, schema: Type[BaseModel]) -> dict[str, Any]:
    # Re-raise the original ValidationError: pydantic v2 errors cannot be
    # constructed from a bare message (the old wrapper crashed with TypeError).
    data = render_markdown_with_frontmatter(md)
    return {**data, "validated_data": schema(**data["frontmatter"])}

def render_markdown_from_file(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as file:
            md = file.read()
        return render_markdown_with_frontmatter(md)
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {path}")

def render_markdown_from_string_with_config(md: str, config: MarkdownConfig) -> str:
    return _render_markdown(md, config)

def bulk_render_markdown(pages: List[str]) -> List[dict[str, Any]]:
    results = []
    for page in pages:
        try:
            results.append(render_markdown_with_frontmatter(page))
        except Exception as e:
            results.append({"error": str(e)})
    return results

def add_render_hook(hook: Callable[[str, dict], None]):
    if not callable(hook):
        raise HookRegistrationError("Hook must be a callable")
    _RENDER_HOOKS.append(hook)

_current_config = MarkdownConfig()
_default_template = "{content}"


def set_render_policy(policy: str = "safe"):
    """Set the active render policy. 'safe' escapes HTML; 'full' renders raw;
    'custom' keeps the current escape setting but marks the policy custom."""
    global _current_config
    if policy not in ("safe", "full", "custom"):
        raise ValueError("Invalid render policy")
    escape = _current_config.escape_html if policy == "custom" else (policy == "safe")
    _current_config = MarkdownConfig(escape_html=escape, render_policy=policy)
    return _current_config


def get_render_config() -> MarkdownConfig:
    return _current_config


def set_default_render_template(template: str):
    """Set the wrapper template applied to rendered HTML ({content} required)."""
    global _default_template
    if "{content}" not in template:
        raise ValueError("template must contain a {content} placeholder")
    _default_template = template
    return _default_template

def get_rendered_html_from_frontmatter(md: str) -> str:
    try:
        data = render_markdown_with_frontmatter(md)
        return data["html"]
    except Exception as e:
        raise MarkdownParseError("Failed to extract HTML from front-matter") from e


# --- grafted from original part (API stability) ---
def render_markdown(md: str) -> str:
    """Small safe Markdown subset (headings, bold, italic, links, paragraphs).
    Escapes HTML first so content can't inject markup."""
    out=[]
    for block in (md or "").split("\n\n"):
        t=html.escape(block.strip())
        t=re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t=re.sub(r"\*(.+?)\*", r"<em>\1</em>", t)
        t=re.sub(r"\[(.+?)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', t)
        m=re.match(r"(#{1,3})\s+(.*)", t)
        if m: lvl=len(m.group(1)); out.append(f"<h{lvl}>{m.group(2)}</h{lvl}>")
        elif t: out.append(f"<p>{t}</p>")
    return "\n".join(out)


def _selftest() -> None:
    """Offline self-test for markdown rendering."""
    # Basic safe rendering escapes injected HTML
    out = render_markdown("# Title\n\nHello **world** <script>alert(1)</script>")
    assert "<h1>Title</h1>" in out
    assert "<strong>world</strong>" in out
    assert "<script>" not in out and "&lt;script&gt;" in out

    # Links only for http(s)
    out = render_markdown("[ok](https://x.io) [bad](javascript:alert(1))")
    assert '<a href="https://x.io">ok</a>' in out
    assert 'href="javascript' not in out

    # Config-driven renderer respects heading level cap
    cfg = MarkdownConfig(max_heading_level=2)
    out = _render_markdown("### Deep heading", cfg)
    assert out == ""
    out = _render_markdown("## Ok heading", cfg)
    assert out == "<h2>Ok heading</h2>"

    # Frontmatter
    doc = "title: Test\nauthor: A\n---\n# Hi\n\nBody **b**"
    data = render_markdown_with_frontmatter(doc)
    assert data["frontmatter"] == {"title": "Test", "author": "A"}
    assert "<h1>Hi</h1>" in data["html"]
    try:
        render_markdown_with_frontmatter("no separator here")
        raise AssertionError("missing frontmatter must raise")
    except InvalidFrontmatterError:
        pass

    # Frontmatter validation via pydantic schema
    class FM(BaseModel):
        title: str
        author: str
    v = render_markdown_with_frontmatter_and_validation(doc, FM)
    assert v["validated_data"].title == "Test"
    try:
        class FM2(BaseModel):
            missing_field: int
        render_markdown_with_frontmatter_and_validation(doc, FM2)
        raise AssertionError("schema mismatch must raise")
    except ValidationError:
        pass

    # Bulk rendering isolates per-page failures
    results = bulk_render_markdown([doc, "broken"])
    assert "html" in results[0] and "error" in results[1]

    # Policy + template + hooks are real
    old_cfg = get_render_config()
    try:
        set_render_policy("full")
        assert get_render_config().escape_html is False
        set_render_policy("safe")
        assert get_render_config().escape_html is True
        try:
            set_render_policy("yolo")
            raise AssertionError("invalid policy must raise")
        except ValueError:
            pass

        set_default_render_template("<article>{content}</article>")
        data = render_markdown_with_frontmatter(doc)
        assert data["html"].startswith("<article>") and data["html"].endswith("</article>")
        try:
            set_default_render_template("no placeholder")
            raise AssertionError("template without placeholder must raise")
        except ValueError:
            pass

        calls = []
        add_render_hook(lambda md, result: calls.append(result["html"]))
        try:
            add_render_hook("not callable")
            raise AssertionError("non-callable hook must raise")
        except HookRegistrationError:
            pass
        render_markdown_with_frontmatter(doc)
        assert len(calls) == 1

        assert get_rendered_html_from_frontmatter(doc) == data["html"]
    finally:
        set_default_render_template("{content}")
        set_render_policy("safe")
        _RENDER_HOOKS.clear()

    # File rendering
    import os
    import tempfile
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        path = os.path.join(tmpdir, "page.md")
        open(path, "w", encoding="utf-8").write(doc)
        assert render_markdown_from_file(path)["frontmatter"]["title"] == "Test"
        try:
            render_markdown_from_file(os.path.join(tmpdir, "nope.md"))
            raise AssertionError("missing file must raise")
        except FileNotFoundError:
            pass

    print("markdown_pages self-test passed")


if __name__ == "__main__":
    _selftest()
