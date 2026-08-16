"""
navbars — Server-side navbar/mobile-menu HTML rendering (Python + jinja2, no react).

### PART-META-JSON
{
  "name": "navbars",
  "layer": "frontend",
  "purpose": "Python/jinja2 server-side HTML rendering of navbars: responsive nav, mobile menu, branding/logo, user profile, search box, icons, role gating and i18n label translation. Default template is embedded (DictLoader); a templates/navbar.html file overrides it when present.",
  "addition": false,
  "status": "core",
  "dependencies": ["jinja2"],
  "inputs": "Brand string, (label, href) link tuples, NavbarConfig options (theme, active, logo_url, user, search_query, icon_map, components, user_role, i18n).",
  "outputs": "HTML strings ready to embed in a page or template.",
  "files_created": [],
  "security_notes": "Jinja2 autoescape is ON and render_navbar escapes via html.escape, so labels/hrefs are XSS-safe; the 'components' dict is deliberately rendered unescaped (marked safe) - pass only trusted, pre-sanitized HTML fragments there, never user input.",
  "ai_usage": "render_navbar(brand, links, active=...) for the simple bar; NavbarConfig + render_navbar_from_config for full features; render_with_i18n(brand, links, i18n_dict={label: translated}).",
  "example": "from scrapyard.frontend.navbars import render_navbar, NavbarConfig, render_navbar_from_config",
  "import_path": "scrapyard.frontend.navbars"
}
### END-PART-META
"""
from __future__ import annotations
import html
from typing import Any, List, Tuple, Optional, Dict

STATUS = "core"

def render_navbar(brand, links, *, active=None):
    e=html.escape
    items=""
    for label, href in links:
        cls=' class="active"' if href==active else ""
        items+=f'<a href="{e(href)}"{cls}>{e(label)}</a>'
    return f'<nav><span class="brand">{e(brand)}</span>{items}</nav>'

class NavbarConfig:
    def __init__(self, brand: str, links: List[Tuple[str, str]], theme: str = "light", active: Optional[str] = None, mobile: bool = False, logo_url: Optional[str] = None, user: Optional[Dict[str, Any]] = None, search_query: Optional[str] = None, icon_map: Optional[Dict[str, str]] = None, components: Optional[Dict[str, str]] = None, user_role: Optional[str] = None, i18n: Optional[Dict[str, str]] = None):
        self.brand = brand
        self.links = links
        self.theme = theme
        self.active = active
        self.mobile = mobile
        self.logo_url = logo_url
        self.user = user
        self.search_query = search_query
        self.icon_map = icon_map
        self.components = components
        self.user_role = user_role
        self.i18n = i18n


# Default template EMBEDDED as a string (DictLoader) so rendering works without
# any templates/ directory; drop a templates/navbar.html file to override it.
DEFAULT_NAVBAR_TEMPLATE = """\
<nav class="navbar theme-{{ navbar.theme }}{% if navbar.mobile %} navbar-mobile{% endif %}">
  {% if navbar.logo_url %}<img class="logo" src="{{ navbar.logo_url }}" alt="{{ navbar.brand }} logo">{% endif %}
  <span class="brand">{{ navbar.brand }}</span>
  {% if navbar.mobile %}<button class="menu-toggle" aria-label="Menu">&#9776;</button>{% endif %}
  <ul class="nav-links">
    {%- for label, href in navbar.links %}
    <li{% if href == navbar.active %} class="active"{% endif %}>
      {%- if navbar.icon_map and label in navbar.icon_map %}<img class="icon" src="{{ navbar.icon_map[label] }}" alt="">{% endif -%}
      <a href="{{ href }}">{{ navbar.i18n.get(label, label) if navbar.i18n else label }}</a>
    </li>
    {%- endfor %}
  </ul>
  {% if navbar.search_query is not none %}<form class="nav-search" method="get"><input type="search" name="q" value="{{ navbar.search_query }}" placeholder="Search"></form>{% endif %}
  {% if navbar.user %}<span class="nav-user">{{ navbar.user.get('name', '') }}</span>{% endif %}
  {% if navbar.components %}{% for name, html_fragment in navbar.components.items() %}<div class="nav-component nav-component-{{ name }}">{{ html_fragment | safe }}</div>{% endfor %}{% endif %}
</nav>
"""


def _navbar_env(template_dir: str = "templates"):
    import os
    from jinja2 import Environment, ChoiceLoader, DictLoader, FileSystemLoader
    loaders = []
    if os.path.isdir(template_dir):
        loaders.append(FileSystemLoader(template_dir))  # optional file override
    loaders.append(DictLoader({"navbar.html": DEFAULT_NAVBAR_TEMPLATE}))
    return Environment(loader=ChoiceLoader(loaders), autoescape=True)


def render_navbar_from_config(config: NavbarConfig, template_dir: str = "templates") -> str:
    env = _navbar_env(template_dir)
    template = env.get_template('navbar.html')
    data = dict(config.__dict__)
    if config.user_role is not None:
        # role gating: links may be (label, href) or (label, href, allowed_roles)
        visible = []
        for link in config.links:
            if len(link) >= 3 and link[2] and config.user_role not in link[2]:
                continue
            visible.append((link[0], link[1]))
        data["links"] = visible
    return template.render(navbar=data)

def render_mobile_menu(brand: str, links: List[Tuple[str, str]], *, active: Optional[str] = None) -> str:
    config = NavbarConfig(
        brand=brand,
        links=links,
        theme="light",  # Default to light theme for mobile
        active=active,
        mobile=True
    )
    return render_navbar_from_config(config)

def render_with_branding(brand: str, links: List[Tuple[str, str]], *, logo_url: Optional[str] = None, theme: str = "light", active: Optional[str] = None) -> str:
    config = NavbarConfig(
        brand=brand,
        links=links,
        theme=theme,
        active=active,
        logo_url=logo_url
    )
    return render_navbar_from_config(config)

def render_with_user_profile(brand: str, links: List[Tuple[str, str]], user: Dict[str, Any], *, active: Optional[str] = None) -> str:
    config = NavbarConfig(
        brand=brand,
        links=links,
        theme="light",
        active=active,
        user=user
    )
    return render_navbar_from_config(config)

def render_with_search(brand: str, links: List[Tuple[str, str]], *, search_query: Optional[str] = None, active: Optional[str] = None) -> str:
    config = NavbarConfig(
        brand=brand,
        links=links,
        theme="light",
        active=active,
        search_query=search_query
    )
    return render_navbar_from_config(config)

def render_with_icons(brand: str, links: List[Tuple[str, str]], *, icon_map: Dict[str, str], active: Optional[str] = None) -> str:
    config = NavbarConfig(
        brand=brand,
        links=links,
        theme="light",
        active=active,
        icon_map=icon_map
    )
    return render_navbar_from_config(config)

def render_with_custom_components(brand: str, links: List[Tuple[str, str]], components: Dict[str, str], *, active: Optional[str] = None) -> str:
    config = NavbarConfig(
        brand=brand,
        links=links,
        theme="light",
        active=active,
        components=components
    )
    return render_navbar_from_config(config)

def render_with_access_control(brand: str, links: List[Tuple[str, str]], user_role: str, *, active: Optional[str] = None) -> str:
    config = NavbarConfig(
        brand=brand,
        links=links,
        theme="light",
        active=active,
        user_role=user_role
    )
    return render_navbar_from_config(config)

def render_with_i18n(brand: str, links: List[Tuple[str, str]], *, i18n_dict: Dict[str, str], active: Optional[str] = None) -> str:
    # fixed: NavbarConfig now accepts i18n; labels are translated in the template
    config = NavbarConfig(
        brand=brand,
        links=links,
        theme="light",
        active=active,
        i18n=i18n_dict,
    )
    return render_navbar_from_config(config)

from jinja2 import Template

navbar_template = Template("""
<nav>
  <span class="brand">{{ navbar.brand }}</span>
  {% if navbar.logo_url %}
    <img src="{{ navbar.logo_url }}" alt="Logo">
  {% endif %}
  <ul>
    {% for label, href in navbar.links %}
      <li{% if href == navbar.active %} class="active"{% endif %}>
        <a href="{{ href }}">{{ label }}</a>
        {% if navbar.icon_map and label in navbar.icon_map %}
          <img src="{{ navbar.icon_map[label] }}" alt="{{ label }}">
        {% endif %}
      </li>
    {% endfor %}
  </ul>
</nav>
""")

def render_navbar_from_template(brand: str, links: List[Tuple[str, str]], *, logo_url: Optional[str] = None, theme: str = "light", active: Optional[str] = None, icon_map: Optional[Dict[str, str]] = None) -> str:
    config = {
        'brand': brand,
        'links': links,
        'theme': theme,
        'active': active,
        'logo_url': logo_url,
        'icon_map': icon_map
    }
    return navbar_template.render(navbar=config)

def render_navbar_with_db(brand: str, links: List[Tuple[str, str]], db_session: Any, *, theme: str = "light", active: Optional[str] = None) -> str:
    """Render using session-scoped user context: reads `db_session.info['user']`
    (SQLAlchemy Session.info dict, e.g. {'name': ..., 'role': ...}) and applies
    the user's name to the profile slot and role to link gating."""
    user = None
    user_role = None
    info = getattr(db_session, "info", None)
    if isinstance(info, dict) and isinstance(info.get("user"), dict):
        user = info["user"]
        user_role = user.get("role")
    config = NavbarConfig(brand=brand, links=links, theme=theme, active=active,
                          user=user, user_role=user_role)
    return render_navbar_from_config(config)


def _selftest() -> bool:
    # simple escaped bar
    out = render_navbar("Acme", [("Home", "/"), ("<x>", "/x")], active="/")
    assert '<span class="brand">Acme</span>' in out
    assert "&lt;x&gt;" in out and "<x>" not in out          # escaped
    assert 'class="active"' in out

    # DictLoader default template renders WITHOUT any templates/ dir on disk
    cfg = NavbarConfig("Acme", [("Home", "/"), ("Docs", "/docs")], active="/docs",
                       logo_url="/logo.png", search_query="", user={"name": "Ada"})
    page = render_navbar_from_config(cfg, template_dir="__no_such_dir__")
    assert 'class="brand"' in page and "Acme" in page
    assert 'src="/logo.png"' in page and 'class="nav-user"' in page and "Ada" in page
    assert '<li class="active">' in page.replace("\n", "")

    # file override wins when templates/navbar.html exists
    import os
    import tempfile
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        with open(os.path.join(td, "navbar.html"), "w", encoding="utf-8") as f:
            f.write("<nav>OVERRIDE {{ navbar.brand }}</nav>")
        assert render_navbar_from_config(cfg, template_dir=td) == "<nav>OVERRIDE Acme</nav>"

    # i18n: labels translated (the kwarg NavbarConfig previously rejected)
    out = render_with_i18n("Acme", [("Home", "/")], i18n_dict={"Home": "Inicio"})
    assert "Inicio" in out and ">Home<" not in out

    # helper renderers all work against the embedded template
    assert "menu-toggle" in render_mobile_menu("A", [("H", "/")])
    assert 'src="/l.png"' in render_with_branding("A", [("H", "/")], logo_url="/l.png")
    assert "Bea" in render_with_user_profile("A", [("H", "/")], {"name": "Bea"})
    assert 'type="search"' in render_with_search("A", [("H", "/")], search_query="q1")
    assert 'class="icon"' in render_with_icons("A", [("H", "/")], icon_map={"H": "/i.svg"})
    out = render_with_custom_components("A", [("H", "/")], {"cta": "<b>Go</b>"})
    assert "<b>Go</b>" in out                              # trusted fragment unescaped

    # role gating drops links the role can't see
    links = [("Home", "/"), ("Admin", "/admin", ["admin"])]
    assert "/admin" not in render_with_access_control("A", links, "viewer")
    assert "/admin" in render_with_access_control("A", links, "admin")

    # XSS: user-controlled label/query escaped by autoescape
    evil = render_navbar_from_config(
        NavbarConfig("A", [("<script>alert(1)</script>", "/")], search_query='"><i>'))
    assert "<script>" not in evil and "&lt;script&gt;" in evil

    # db-session variant reads Session.info
    class FakeSession:
        info = {"user": {"name": "Cy", "role": "admin"}}
    out = render_navbar_with_db("A", links, FakeSession())
    assert "Cy" in out and "/admin" in out

    # legacy inline-template renderer still works
    out = render_navbar_from_template("A", [("H", "/")], icon_map={"H": "/i.png"})
    assert "<nav>" in out and 'href="/"' in out

    print("navbars selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
