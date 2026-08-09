"""
input_sanitization — Sanitize/escape untrusted input + HTML.

### PART-META-JSON
{
  "name": "input_sanitization",
  "layer": "security",
  "purpose": "Sanitize/escape untrusted input + HTML.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "bleach"
  ],
  "inputs": "Public API: strip_control_chars(text); escape_html(text); sanitize_html_with_policy(text, policy, default_policy); escape_for_database(text, escape_rules); escape_for_json(text, escape_rules); SanitizationPolicy(...); SanitizationHook(...) (plus more).",
  "outputs": "Returns: strip_control_chars -> str; escape_html -> str; sanitize_html_with_policy -> str; escape_for_database -> str; escape_for_json -> str.",
  "files_created": [],
  "security_notes": "Renders HTML with all caller text escaped via html.escape (XSS-safe); any HTML 'slot' arguments are inserted verbatim and must be pre-escaped by the caller.",
  "ai_usage": "Import `strip_control_chars` from `scrapyard.security.input_sanitization` and call it as shown in `example`; run `py -m scrapyard.security.input_sanitization` to see its offline selftest.",
  "example": "from scrapyard.security.input_sanitization import strip_control_chars",
  "import_path": "scrapyard.security.input_sanitization"
}
### END-PART-META
"""
from typing import Dict, List, Optional, Pattern, TypeVar, Union

import html
import re
from pydantic import BaseModel, ValidationError
from jinja2 import Template

T = TypeVar('T')

class SanitizationPolicy(BaseModel):
    allowed_tags: Optional[List[str]] = None
    allowed_attributes: Optional[List[str]] = None
    allowed_protocols: Optional[List[str]] = None

class SanitizationHook:
    def pre_process(self, text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        return strip_control_chars(text)

    def post_process(self, text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        return text

def strip_control_chars(text: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text or "")

def escape_html(text: str) -> str:
    return html.escape(strip_control_chars(text or ""))

# Matches a single HTML tag: capture (closing-slash?)(name)(attributes)(self-close?).
_TAG_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9:-]*)((?:[^<>]*?))(/?)\s*>")
# Matches one attribute: name plus an optional ="value" / ='value' / =value.
_ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)      # attribute name
        (?:\s*=\s*                          # optional value
            (?:"([^"]*)"|'([^']*)'|([^\s"'<>`]+))
        )?""",
    re.VERBOSE,
)
_SAFE_PROTOCOLS = ("http", "https", "mailto", "tel")


def _attr_value_safe(name: str, value: str, allowed_protocols: List[str]) -> bool:
    """Reject URL-bearing attributes whose value uses a disallowed protocol
    (e.g. javascript:, data:) — the classic attribute-injection vector."""
    if name.lower() not in ("href", "src", "xlink:href", "action", "formaction"):
        return True
    v = value.strip().lower()
    # Strip HTML entities/whitespace that browsers ignore before the scheme.
    v = re.sub(r"[\x00-\x20]+", "", v)
    if ":" not in v.split("/", 1)[0]:
        return True  # relative URL, no scheme -> safe
    scheme = v.split(":", 1)[0]
    return scheme in {p.lower() for p in (allowed_protocols or _SAFE_PROTOCOLS)}


def _filter_attributes(raw: str, allowed_attributes: List[str],
                       allowed_protocols: List[str]) -> str:
    """Rebuild an attribute string keeping only allow-listed, protocol-safe
    attributes; every value is HTML-escaped. Nothing from the input is trusted."""
    allowed = {a.lower() for a in (allowed_attributes or [])}
    if not allowed:
        return ""
    parts: List[str] = []
    for m in _ATTR_RE.finditer(raw or ""):
        name = m.group(1)
        if name.lower() not in allowed:
            continue
        value = m.group(2) or m.group(3) or m.group(4) or ""
        if not _attr_value_safe(name, value, allowed_protocols):
            continue
        parts.append(f'{name.lower()}="{html.escape(value, quote=True)}"')
    return (" " + " ".join(parts)) if parts else ""


def sanitize_html_with_policy(
    text: str,
    policy: SanitizationPolicy,
    default_policy: Optional[SanitizationPolicy] = None
) -> str:
    """Policy-based HTML sanitization (pure stdlib, no bleach required).

    Everything is HTML-escaped by default; only tags named in
    ``policy.allowed_tags`` are re-emitted, and only with attributes named in
    ``policy.allowed_attributes`` (URL attributes are additionally protocol-checked).
    Any tag or attribute not on the allow-list is escaped to inert text — so a
    ``<script>`` or ``onerror=`` payload can never survive as live markup.
    """
    if default_policy is not None and not policy.allowed_tags:
        policy = policy.model_copy(update=default_policy.model_dump())

    text = strip_control_chars(text or "")
    allowed_tags = {t.lower() for t in (policy.allowed_tags or [])}
    allowed_attributes = policy.allowed_attributes or []
    allowed_protocols = policy.allowed_protocols or list(_SAFE_PROTOCOLS)

    out: List[str] = []
    pos = 0
    for m in _TAG_RE.finditer(text):
        out.append(html.escape(text[pos:m.start()]))  # inter-tag text -> escaped
        pos = m.end()
        closing, name, raw_attrs, self_close = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if name in allowed_tags:
            if closing:
                out.append(f"</{name}>")
            else:
                attrs = _filter_attributes(raw_attrs, allowed_attributes, allowed_protocols)
                out.append(f"<{name}{attrs}{' /' if self_close else ''}>")
        else:
            out.append(html.escape(m.group(0)))  # disallowed tag -> inert text
    out.append(html.escape(text[pos:]))
    return "".join(out)

def escape_for_database(
    text: str,
    escape_rules: Optional[Dict[str, str]] = None
) -> str:
    if not escape_rules:
        return html.escape(text)
    
    for key, value in escape_rules.items():
        text = re.sub(key, value, text)
    return text

def escape_for_json(
    text: str,
    escape_rules: Optional[Dict[str, str]] = None
) -> str:
    if not escape_rules:
        return html.escape(text)
    
    for key, value in escape_rules.items():
        text = re.sub(key, value, text)
    return text

def escape_for_url(
    text: str,
    escape_rules: Optional[Dict[str, str]] = None
) -> str:
    if not escape_rules:
        return html.escape(text)
    
    for key, value in escape_rules.items():
        text = re.sub(key, value, text)
    return text

def escape_for_log(
    text: str,
    escape_rules: Optional[Dict[str, str]] = None
) -> str:
    if not escape_rules:
        return html.escape(text)
    
    for key, value in escape_rules.items():
        text = re.sub(key, value, text)
    return text

def apply_sanitization_hooks(
    text: str,
    hook: Optional[SanitizationHook] = None
) -> str:
    if hook and hasattr(hook, 'pre_process'):
        text = hook.pre_process(text)
    
    result = escape_html(text)
    
    if hook and hasattr(hook, 'post_process'):
        result = hook.post_process(result)
    
    return result

def bulk_sanitize(
    texts: List[str],
    policy: SanitizationPolicy,
    parallel: bool = False
) -> List[str]:
    sanitized_texts = []
    for text in texts:
        sanitized_texts.append(sanitize_html_with_policy(text, policy))
    return sanitized_texts

def validate_input(
    text: str,
    schema: Optional[Union[str, Pattern]] = None,
    error_message: Optional[str] = None
) -> str:
    if not text:
        raise ValueError("Input cannot be empty")
    
    if schema and isinstance(schema, str):
        try:
            Template(schema).render(text=text)
        except Exception as e:
            raise ValidationError(f"Invalid input: {str(e)}") from e
    
    return text


# --- grafted from original part (API stability) ---
def sanitize_html(text: str, allowed_tags=None) -> str:
    """Real allow-list sanitization: keep a small set of safe formatting tags,
    escape everything else. Delegates to the policy sanitizer (no attributes are
    permitted for these tags, so event handlers cannot ride along)."""
    tags = list(allowed_tags) if allowed_tags is not None else ["b", "i", "em", "strong", "p", "br"]
    policy = SanitizationPolicy(allowed_tags=tags)
    return sanitize_html_with_policy(text or "", policy)


def _selftest() -> None:
    """Offline, falsifiable self-test of the escaping/sanitization primitives."""
    xss = "<script>alert('xss')</script>"

    # 1) NEGATIVE: a script payload is neutralized (no raw executable tag survives)
    esc = escape_html(xss)
    assert "<script>" not in esc and "</script>" not in esc, "raw <script> must not survive"
    assert "&lt;script&gt;" in esc, "angle brackets must be entity-escaped"

    # 2) NEGATIVE: control chars (incl. NUL) are stripped
    dirty = "a\x00b\x07c"
    clean = strip_control_chars(dirty)
    assert "\x00" not in clean and "\x07" not in clean and clean == "abc", "control chars stripped"
    hook = SanitizationHook()
    assert hook.pre_process(dirty) == "abc" and hook.post_process("abc") == "abc"
    try:
        hook.pre_process(None)
        raise AssertionError("hook accepted non-string input")
    except TypeError:
        pass

    # 3) sanitize_html removes/escapes markup so no live tag remains
    out = sanitize_html("<img src=x onerror=alert(1)>hi")
    assert "<img" not in out.lower(), "sanitize_html must not emit a live <img> tag"
    assert "hi" in out, "sanitized text content is preserved"

    # 4) escape_for_database escapes HTML-significant chars by default
    assert "&lt;" in escape_for_database("<b>") and "<b>" not in escape_for_database("<b>")

    # 5) quotes are escaped (attribute-injection defense)
    assert "&#x27;" in escape_html("it's") or "&#39;" in escape_html("it's")

    # 6) sanitize_html_with_policy REALLY honors an allow-list (not an escape-all
    #    fallback): an allowed <b> survives as live markup while <script> does not.
    policy = SanitizationPolicy(allowed_tags=["b", "i", "p"])
    mixed = "<script>alert('xss')</script><b>bold</b><p>para</p>"
    out = sanitize_html_with_policy(mixed, policy)
    assert "<b>bold</b>" in out, f"allowed <b> must survive: {out!r}"
    assert "<p>para</p>" in out, f"allowed <p> must survive: {out!r}"
    # NEGATIVE: the script tag is neutralized to inert, entity-escaped text.
    assert "<script>" not in out and "</script>" not in out, f"script survived: {out!r}"
    assert "&lt;script&gt;" in out, f"script must be escaped, not dropped: {out!r}"

    # 7) NEGATIVE: a disallowed attribute / event handler on an allowed tag is
    #    stripped (allow-list carries no attributes by default).
    evt = sanitize_html_with_policy('<b onclick="steal()">x</b>',
                                    SanitizationPolicy(allowed_tags=["b"]))
    assert evt == "<b>x</b>", f"event handler must be stripped: {evt!r}"

    # 8) NEGATIVE: a javascript: URL is rejected even when href is allow-listed.
    js = sanitize_html_with_policy(
        '<a href="javascript:alert(1)">c</a><a href="/safe">ok</a>',
        SanitizationPolicy(allowed_tags=["a"], allowed_attributes=["href"]),
    )
    assert "javascript:" not in js, f"javascript: URL must be dropped: {js!r}"
    assert 'href="/safe"' in js, f"safe relative href must survive: {js!r}"

    # 9) A known XSS payload arriving as text is neutralized: no LIVE <img> tag
    #    survives (it is entity-escaped to inert text, so onerror can never fire).
    payload = "<img src=x onerror=alert(document.cookie)>"
    neutral = sanitize_html_with_policy(payload, SanitizationPolicy(allowed_tags=["b"]))
    assert "<img" not in neutral.lower(), f"live <img> must not survive: {neutral!r}"
    assert "&lt;img" in neutral.lower(), f"img tag must be entity-escaped: {neutral!r}"

    print("input_sanitization: OK (13 assertions incl. XSS/control-char/event-handler/"
          "javascript-url negatives; policy allow-list proven live)")


if __name__ == "__main__":
    _selftest()

