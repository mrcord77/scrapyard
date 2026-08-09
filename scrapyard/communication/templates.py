"""
templates — Render notification templates (text/html).

### PART-META-JSON
{
  "name": "templates",
  "layer": "communication",
  "purpose": "Render notification templates (text/html).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "jinja2"
  ],
  "inputs": "Public API: get_jinja_env(); render_template(template_name, context, *, env); render_from_string(template, context, *, env); render_bulk(templates, *, env); get_template(name, *, env); TemplateNotFoundError(...) (plus more).",
  "outputs": "Returns: get_jinja_env -> Environment; render_template -> str; render_from_string -> str; render_bulk -> list[str]; get_template -> Template.",
  "files_created": [],
  "security_notes": "Renders HTML with all caller text escaped via html.escape (XSS-safe); any HTML 'slot' arguments are inserted verbatim and must be pre-escaped by the caller. Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import `get_jinja_env` from `scrapyard.communication.templates` and call it as shown in `example`; run `py -m scrapyard.communication.templates` to see its offline selftest.",
  "example": "from scrapyard.communication.templates import get_jinja_env",
  "import_path": "scrapyard.communication.templates"
}
### END-PART-META
"""
import html
from typing import *
from jinja2 import Environment, Template, TemplateNotFound, DictLoader, select_autoescape

STATUS = "core"

# Module-level default environment (a DictLoader callers can populate).
_default_env: Optional[Environment] = None


def get_jinja_env() -> Environment:
    """Return the shared default Jinja environment (autoescaping HTML)."""
    global _default_env
    if _default_env is None:
        _default_env = Environment(loader=DictLoader({}),
                                   autoescape=select_autoescape(["html", "xml"]))
    return _default_env

def render_template(template_name: str, context: dict, /, *, env: Environment = None) -> str:
    if env is None:
        from scrapyard.communication.templates import get_jinja_env  # Lazy import
        env = get_jinja_env()
    
    template = env.get_template(template_name)
    return template.render(context)

def render_from_string(template: str, context: dict, /, *, env: Environment = None) -> str:
    if env is None:
        from scrapyard.communication.templates import get_jinja_env  # Lazy import
        env = get_jinja_env()
    
    # Compile within the environment so registered filters/globals apply
    # (a bare Template() ignores the env entirely).
    return env.from_string(template).render(context)

def render_bulk(templates: list[tuple[str, dict]], /, *, env: Environment = None) -> list[str]:
    if env is None:
        from scrapyard.communication.templates import get_jinja_env  # Lazy import
        env = get_jinja_env()
    
    results = []
    for template_name, context in templates:
        try:
            template = env.get_template(template_name)
            results.append(template.render(context))
        except TemplateNotFound as e:
            raise TemplateNotFoundError(f"Template {template_name} not found") from e
    return results

def get_template(name: str, /, *, env: Environment = None) -> Template:
    if env is None:
        from scrapyard.communication.templates import get_jinja_env  # Lazy import
        env = get_jinja_env()
    
    try:
        template = env.get_template(name)
    except TemplateNotFound as e:
        raise TemplateNotFoundError(f"Template {name} not found") from e
    
    return template

def register_filter(name: str, func: Callable, /, *, env: Environment = None) -> None:
    if env is None:
        from scrapyard.communication.templates import get_jinja_env  # Lazy import
        env = get_jinja_env()
    
    env.filters[name] = func

def register_global(name: str, value: Any, /, *, env: Environment = None) -> None:
    if env is None:
        from scrapyard.communication.templates import get_jinja_env  # Lazy import
        env = get_jinja_env()
    
    env.globals[name] = value

def template_from_string(template: str, /, *, env: Environment = None) -> Template:
    if env is None:
        from scrapyard.communication.templates import get_jinja_env  # Lazy import
        env = get_jinja_env()
    
    return env.from_string(template)

def render_with_policy(template: str, context: dict, policy: dict, /, *, env: Environment = None) -> str:
    if env is None:
        from scrapyard.communication.templates import get_jinja_env  # Lazy import
        env = get_jinja_env()
    
    return _render_with_policy(env.from_string(template), context, policy)

def _render_with_policy(template: Template, context: dict, policy: dict) -> str:
    """Apply the render policy: escape string values (default on) and redact
    any keys listed in policy['redact_fields']."""
    from markupsafe import Markup

    escape_values = policy.get("escape_html", True)
    redact_fields = set(policy.get("redact_fields", ()))

    def transform(key, value):
        if key in redact_fields:
            return "***"
        if escape_values and isinstance(value, str):
            # Markup marks the pre-escaped text safe so an autoescaping
            # environment does not escape it a second time.
            return Markup(html.escape(value))
        if escape_values and isinstance(value, bytes):
            return Markup(html.escape(value.decode("utf-8", "replace")))
        if not escape_values and isinstance(value, str):
            # Caller explicitly opted out of escaping: emit verbatim.
            return Markup(value)
        return value

    new_context = {k: transform(k, v) for k, v in context.items()}
    return template.render(new_context)

def audit_render(func: Callable, /, *, log_context: bool = True) -> Callable:
    import logging
    logger = logging.getLogger(__name__)
    
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        if log_context and 'context' in kwargs:
            logger.info(f"Rendered template with context: {kwargs['context']}")
        return result
    
    return wrapper

def render_to_file(template: str, context: dict, output_path: str, /, *, env: Environment = None) -> None:
    if env is None:
        from scrapyard.communication.templates import get_jinja_env  # Lazy import
        env = get_jinja_env()
    
    rendered_content = env.from_string(template).render(context)
    
    with open(output_path, 'w', encoding='utf-8') as file:
        file.write(rendered_content)

class TemplateNotFoundError(Exception):
    pass


# --- grafted from original part (API stability) ---
import re

_VAR = re.compile(r"{{\s*(\w+)\s*}}")

def render(template: str, **vars) -> str:
    """Minimal {{var}} substitution with HTML-safe values by default."""
    import html
    def repl(m):
        key = m.group(1)
        if key not in vars:
            raise KeyError(f"missing template var: {key}")
        return html.escape(str(vars[key]))
    return _VAR.sub(repl, template)

def render_raw(template: str, **vars) -> str:
    return _VAR.sub(lambda m: str(vars[m.group(1)]), template)


def _selftest() -> None:
    """Offline self-test for template rendering."""
    # Minimal {{var}} renderer (HTML-safe by default)
    assert render("Hi {{name}}", name="<b>x</b>") == "Hi &lt;b&gt;x&lt;/b&gt;"
    assert render_raw("Hi {{name}}", name="<b>") == "Hi <b>"
    try:
        render("{{missing}}")
        raise AssertionError("missing var must raise KeyError")
    except KeyError:
        pass

    # Default env: register a template and render it. Use the canonical
    # module's env (the lazy imports inside the render functions resolve to
    # scrapyard.communication.templates even when this file runs as __main__).
    from scrapyard.communication import templates as _canonical
    env = _canonical.get_jinja_env()
    env.loader.mapping["welcome.html"] = "Hello {{ user }}!"
    assert render_template("welcome.html", {"user": "Ada"}) == "Hello Ada!"
    assert render_from_string("{{ a }}+{{ b }}", {"a": 1, "b": 2}) == "1+2"
    assert render_bulk([("welcome.html", {"user": "Bob"})]) == ["Hello Bob!"]
    try:
        get_template("nope.html")
        raise AssertionError("missing template must raise")
    except TemplateNotFoundError:
        pass

    # Filters and globals
    register_filter("shout", lambda s: str(s).upper())
    assert render_from_string("{{ 'hi' | shout }}", {}) == "HI"
    register_global("brand", "Scrapyard")
    assert render_from_string("{{ brand }}", {}) == "Scrapyard"

    # Policy rendering: escapes strings, redacts listed fields
    out = render_with_policy("{{ name }} {{ ssn }}",
                             {"name": "<i>x</i>", "ssn": "123-45-6789"},
                             {"redact_fields": ["ssn"]})
    assert out == "&lt;i&gt;x&lt;/i&gt; ***"
    out = render_with_policy("{{ v }}", {"v": "<raw>"}, {"escape_html": False})
    assert out == "<raw>"

    # render_to_file writes rendered output
    import os
    import tempfile
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        path = os.path.join(tmpdir, "out.txt")
        render_to_file("v={{ v }}", {"v": 7}, path)
        assert open(path, encoding="utf-8").read() == "v=7"

    print("templates self-test passed")


if __name__ == "__main__":
    _selftest()
