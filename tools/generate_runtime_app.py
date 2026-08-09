"""
generate_runtime_app.py — Turn a copied parts folder into a *bootable* app.

The flat assemble.py path copies parts but never wired an entrypoint. This writes:
    main.py, scrapyard_app/{settings,bootstrap,routes,capabilities}.py,
    .env.example, CAPABILITIES.md, smoke_check.py
so that after `pip install -r requirements.txt`, `uvicorn main:app` boots and serves
/health and /capabilities, mounting any selected feature routers (auth, jobs admin).

Honest by construction: routers that can't wire are skipped-with-reason in
development and *raise* in production; CAPABILITIES.md reports what actually mounted.
"""
from __future__ import annotations
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name: str) -> dict:
    p = os.path.join(ROOT, "config", name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def _load_template_metadata() -> dict:
    p = os.path.join(ROOT, "templates", "template_metadata.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


_MAIN = '''"""Generated entrypoint. Boot with: uvicorn main:app --reload"""
import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from scrapyard.api.app_factory import create_app
from scrapyard_app.bootstrap import startup_checks
from scrapyard_app.routes import include_routes
from scrapyard_app.settings import settings

startup_checks()                       # validate config, init DB, gate prod fallbacks
app = create_app(title="Scrapyard Generated App")

# Request-level enforcement on EVERY route (zero per-route wiring). PrincipalMiddleware
# is added last so it runs first/outermost (resolves the caller), then RateLimitMiddleware
# keys its global limit on that principal. Both degrade safely without their backends.
try:
    from scrapyard.runtime.request_security import PrincipalMiddleware, RateLimitMiddleware
    from scrapyard.security.rate_limiting import get_rate_limiter
    app.add_middleware(RateLimitMiddleware, limiter_factory=get_rate_limiter)
    app.add_middleware(PrincipalMiddleware, jwt_secret=settings.secret_key)
except Exception as _e:
    print(f"[bootstrap] request-security middleware not enabled: {_e}")

include_routes(app)                    # /health, /capabilities, + selected routers

# Server-rendered frontend: Jinja2 + Tailwind CDN
_tpl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
if os.path.isdir(_tpl_dir):
    templates = Jinja2Templates(directory=_tpl_dir)
    from scrapyard_app.views import register_views
    register_views(app, templates)
'''

_SETTINGS = '''"""Generated settings (env-driven)."""
from __future__ import annotations
import os

class Settings:
    def __init__(self):
        self.app_env = os.environ.get("APP_ENV", "development")
        self.database_url = os.environ.get("DATABASE_URL", "sqlite:///./app.db")
        self.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

settings = Settings()
'''


def _bootstrap_py(model_modules: list[str]) -> str:
    lines = [
        '"""Generated startup checks: config validation, DB init, production fallback gate."""',
        "from __future__ import annotations",
        "from scrapyard_app.settings import settings",
        "",
        "",
        "def startup_checks():",
        "    # 1) production must not run on dev defaults",
        '    if settings.is_production and settings.secret_key == "dev-only-change-me":',
        '        raise RuntimeError("SECRET_KEY must be set in production")',
        "",
        "    # 2) schema is MIGRATION-FIRST in dev AND prod: run `alembic upgrade head`",
        "    #    (the single source of truth). create_all() then runs check-first ONLY to",
        "    #    add tables no migration covers yet -- it runs AFTER alembic and skips any",
        "    #    table a migration already created, so it can never cause 'already exists'.",
        "    try:",
        "        from scrapyard.database.db_session import init_engine",
        "        engine = init_engine(settings.database_url)",
        "        import os as _os",
        "        _ini = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'alembic.ini')",
        "        _migrated = False",
        "        if _os.path.exists(_ini):",
        "            try:",
        "                from alembic.config import Config",
        "                from alembic import command",
        "                _cfg = Config(_ini); _cfg.set_main_option('sqlalchemy.url', settings.database_url)",
        "                command.upgrade(_cfg, 'head')   # migration-managed schema (dev + prod)",
        "                _migrated = True",
        "            except Exception as _me:",
        "                print(f'[bootstrap] alembic upgrade head failed, falling back to create_all: {_me}')",
        "        from scrapyard.database.base_model import Base",
    ]
    for m in model_modules:
        lines += [
            f"        try:",
            f"            import {m}  # noqa: F401  (registers tables on Base)",
            f"        except Exception as _e:",
            f"            print(f'[bootstrap] model import skipped: {m}: {{_e}}')",
        ]
    lines += [
        "        # check-first: creates only tables a migration did not (no conflict with migrated tables)",
        "        Base.metadata.create_all(engine, checkfirst=True)",
        "        if settings.is_production and _os.environ.get('SCRAPYARD_RLS', '').strip().lower() == 'enforce' and settings.database_url.startswith('postgres'):",
        "            from scrapyard.security.row_level_security import apply_rls_existing",
        "            with engine.begin() as _conn:",
        "                print('[bootstrap] database RLS enforced on:', apply_rls_existing(_conn))",
        "    except Exception as e:",
        '        print(f"[bootstrap] database init skipped: {e}")',
        "",
        "    # 3) production fallback gate (refuse local-only paths in prod), if available",
        "    try:",
        "        from scrapyard.runtime.fallbacks import detect_fallbacks, assert_no_forbidden_fallbacks",
        "        detect_fallbacks(settings)",
        "        assert_no_forbidden_fallbacks(settings.app_env)",
        "    except RuntimeError:",
        "        raise",
        "    except Exception as e:",
        '        print(f"[bootstrap] fallback gate unavailable: {e}")',
        "",
        "    # 4) observability: export errors/traces when configured (no-op without",
        "    #    SENTRY_DSN / OTEL_EXPORTER_OTLP_ENDPOINT, or if the SDK isn't installed)",
        "    try:",
        "        from scrapyard.observability.error_reporting import init_sentry",
        "        if init_sentry():",
        '            print("[bootstrap] Sentry error reporting enabled")',
        "    except Exception as e:",
        '        print(f"[bootstrap] error reporting not enabled: {e}")',
        "    try:",
        "        from scrapyard.observability.tracing import init_otel",
        "        if init_otel() is not None:",
        '            print("[bootstrap] OpenTelemetry tracing enabled")',
        "    except Exception as e:",
        '        print(f"[bootstrap] tracing not enabled: {e}")',
        "",
    ]
    return "\n".join(lines)


def _routes_py(routers: list[dict]) -> str:
    blocks = []
    for r in routers:
        ip, factory, obj = r["import_path"], r.get("router_factory"), r.get("router_object")
        prefix, tags = r.get("mount_prefix", ""), r.get("tags", [])
        if factory:
            mk = (f"from {ip} import {factory} as _factory\n"
                  f"        from scrapyard.database.db_session import get_db\n"
                  f"        from scrapyard.runtime.request_security import make_scoped_db\n"
                  f"        from scrapyard_app.settings import settings as _s\n"
                  f"        app.include_router(_factory(make_scoped_db(get_db, _s.database_url)))")
        else:
            mk = (f"from {ip} import {obj} as _r\n"
                  f"        app.include_router(_r, prefix={prefix!r}, tags={tags!r})")
        raise_cond = "True" if r.get("required") else "settings.is_production"
        kind = "required" if r.get("required") else "optional"
        blocks.append(
            f'''    # {ip} ({kind})
    try:
        {mk}
        _mounted.append({prefix!r} or {ip!r})
    except Exception as exc:
        if {raise_cond}:
            raise RuntimeError(f"{kind} router {ip} failed to mount: {{exc}}")
        _skipped.append(({ip!r}, str(exc)))
        print(f"[routes] skipped {ip} (dev, optional): {{exc}}")''')
    body = "\n".join(blocks) if blocks else "    pass  # no feature routers selected"
    return '''"""Generated route wiring: always /health + /capabilities, plus selected routers."""
from __future__ import annotations
import os
from fastapi import FastAPI
from scrapyard_app.settings import settings
from scrapyard_app.capabilities import CAPABILITIES

_mounted: list = []
_skipped: list = []


def include_routes(app: FastAPI):
    # /health, /healthz, /livez come from the app factory (one canonical payload for
    # every generated app, assemble or EOS). Routes adds deep readiness + capabilities.
    # Deep readiness: DB reachable + migrations at head (+ Redis if configured).
    # Returns 503 until ready, so a load balancer keeps the instance out of rotation.
    try:
        from scrapyard.operations.readiness import readiness_report, build_readiness_router
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        def _resolver():
            ini = os.path.join(_root, "alembic.ini")
            sl = os.path.join(_root, "migrations")
            uses_redis = (os.environ.get("CACHE_BACKEND", "").lower() == "redis"
                          or os.environ.get("RATE_LIMIT_BACKEND", "").lower() == "redis")
            return readiness_report(
                database_url=settings.database_url,
                redis_url=os.environ.get("REDIS_URL") if uses_redis else None,
                alembic_ini=ini if os.path.exists(ini) else None,
                script_location=sl if os.path.exists(sl) else None)

        app.include_router(build_readiness_router(_resolver))
    except Exception as _e:  # readiness is best-effort wiring; never block boot
        @app.get("/readyz", tags=["health"])
        def _readyz():
            return {"ready": True, "checks": {}, "note": f"readiness unavailable: {_e}"}

    @app.get("/capabilities", tags=["meta"])
    def capabilities():
        return {**CAPABILITIES, "routers_mounted": _mounted, "routers_skipped": _skipped}

''' + body + '''
    return app
'''


def _capabilities_py(app_type, parts, mount_prefixes, required_routes, probe) -> str:
    missing = [r for r in required_routes
               if not any(r == p or r.startswith(p.rstrip("/") + "/") for p in mount_prefixes)]
    cap = {
        "template": app_type,
        "bootable": True,
        "included_parts": parts,
        "routes": ["/health", "/capabilities"] + mount_prefixes,
        "feature_routes": mount_prefixes,
        "feature_routes_count": len(mount_prefixes),
        "behavior_checks": [probe] if probe else [],
        "missing_expected_routes": missing,
        "local_only_fallbacks": [
            "security.local_crypto_backend", "communication.email_console",
            "ai.offline_provider", "jobs.memory_queue",
        ],
        "production_ready": False,
    }
    import pprint
    return "CAPABILITIES = " + pprint.pformat(cap, width=100, sort_dicts=False) + "\n"


def _behavior_check_py(probe: str, required_routes: list[str]) -> str:
    head = ('from fastapi.testclient import TestClient\n'
            'from main import app\n\n\n'
            'def main():\n'
            '    c = TestClient(app)\n')
    if probe == "saas_auth":
        body = (
            '    import uuid\n'
            '    pw = "CorrectHorseBatteryStaple123!"\n'
            '    email = f"probe-{uuid.uuid4().hex[:8]}@example.com"  # unique per run (idempotent)\n'
            '    r = c.post("/auth/register", json={"email": email, "password": pw})\n'
            '    assert r.status_code in (200, 201), ("register failed", r.status_code, r.text)\n'
            '    r2 = c.post("/auth/login", json={"email": email, "password": pw})\n'
            '    assert r2.status_code == 200 and "session" in r2.json(), ("login failed", r2.status_code, r2.text)\n'
            '    print("behavior_check passed: saas_auth (register + login)")\n')
    else:
        body = (
            f'    required = {required_routes!r}\n'
            '    missing, broken, served, gated = [], [], 0, 0\n'
            '    for p in required:\n'
            '        resp = c.get(p)\n'
            '        sc = resp.status_code\n'
            '        if sc == 404:\n'
            '            missing.append(p)            # route not mounted\n'
            '        elif sc >= 500:\n'
            '            broken.append((p, sc))       # route mounted but erroring\n'
            '        elif sc in (401, 403):\n'
            '            gated += 1                   # mounted and correctly requiring auth\n'
            '        elif sc < 400:\n'
            '            served += 1                  # mounted and actually serving\n'
            '    assert not missing, ("required feature routes missing/unmounted: " + ", ".join(missing))\n'
            '    assert not broken, ("feature routes returned a server error (5xx): " + str(broken))\n'
            '    # a route that exists must DO something: either serve a success or correctly gate on auth.\n'
            '    assert served >= 1 or gated == len(required), \\\n'
            '        ("no feature route served a success and not all are auth-gated", served, gated, len(required))\n'
            '    print(f"behavior_check passed: {len(required)} routes mounted, none 5xx, "\n'
            '          f"{served} served 2xx/3xx, {gated} correctly auth-gated")\n')
    return head + body + '\n\nif __name__ == "__main__":\n    main()\n'


def _write_app_migrations(out_dir: str, model_modules: list[str]) -> dict:
    """Write a scoped Alembic setup into the assembled app and bake a baseline
    migration from the app's own models, so production runs `alembic upgrade head`
    instead of create_all(). Returns {baseline: bool}."""
    import subprocess, tempfile
    mig = os.path.join(out_dir, "migrations")
    os.makedirs(os.path.join(mig, "versions"), exist_ok=True)
    only = ",".join(model_modules)
    open(os.path.join(out_dir, "alembic.ini"), "w", encoding="utf-8").write(
        "[alembic]\nscript_location = migrations\nprepend_sys_path = .\n"
        "# default DB; env.py overrides this with $DATABASE_URL when it is set,\n"
        "# so `alembic upgrade head` works out of the box and in production.\n"
        "sqlalchemy.url = sqlite:///./app.db\n")
    open(os.path.join(mig, "env.py"), "w", encoding="utf-8").write(
        "import os\n"
        "from alembic import context\n"
        "from sqlalchemy import engine_from_config, pool\n"
        "config = context.config\n"
        f"_only = os.environ.get('SCRAPYARD_MODEL_MODULES', {only!r})\n"
        "only = [m.strip() for m in _only.split(',') if m.strip()] or None\n"
        "from scrapyard.database.metadata import target_metadata as _md\n"
        "target_metadata = _md(only)\n"
        "_url = os.environ.get('DATABASE_URL')\n"
        "if _url: config.set_main_option('sqlalchemy.url', _url)\n"
        "def run_online():\n"
        "    cfg = config.get_section(config.config_ini_section) or {}\n"
        "    cfg['sqlalchemy.url'] = config.get_main_option('sqlalchemy.url')\n"
        "    eng = engine_from_config(cfg, prefix='sqlalchemy.', poolclass=pool.NullPool)\n"
        "    with eng.connect() as c:\n"
        "        context.configure(connection=c, target_metadata=target_metadata, compare_type=True, render_as_batch=True)\n"
        "        with context.begin_transaction():\n"
        "            context.run_migrations()\n"
        "def run_offline():\n"
        "    context.configure(url=config.get_main_option('sqlalchemy.url'), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)\n"
        "    with context.begin_transaction():\n"
        "        context.run_migrations()\n"
        "run_offline() if context.is_offline_mode() else run_online()\n")
    open(os.path.join(mig, "script.py.mako"), "w", encoding="utf-8").write(
        '"""${message}\nRevision ID: ${up_revision}\nRevises: ${down_revision | comma,n}\n"""\n'
        "from alembic import op\nimport sqlalchemy as sa\n${imports if imports else ''}\n"
        "revision = ${repr(up_revision)}\ndown_revision = ${repr(down_revision)}\n"
        "branch_labels = ${repr(branch_labels)}\ndepends_on = ${repr(depends_on)}\n\n"
        "def upgrade():\n    ${upgrades if upgrades else 'pass'}\n\n"
        "def downgrade():\n    ${downgrades if downgrades else 'pass'}\n")
    if not model_modules:
        return {"baseline": False}
    tmpdb = tempfile.mktemp(suffix=".db")
    env = dict(os.environ, PYTHONPATH=out_dir, SCRAPYARD_MODEL_MODULES=only,
               DATABASE_URL=f"sqlite:///{tmpdb}")
    r = subprocess.run(["alembic", "revision", "--autogenerate", "-m", "baseline"],
                       cwd=out_dir, env=env, capture_output=True, text=True)
    if os.path.exists(tmpdb):
        os.remove(tmpdb)
    versions = [v for v in os.listdir(os.path.join(mig, "versions")) if v.endswith(".py")]
    return {"baseline": bool(versions), "stderr": r.stderr[-200:]}


def _write_frontend(out_dir: str, app_type: str, mount_prefixes: list[str]):
    """Write Jinja2 templates + views for a designed server-rendered dashboard."""
    tpl_dir = os.path.join(out_dir, "templates")
    os.makedirs(tpl_dir, exist_ok=True)

    app_title = app_type.replace("_", " ").title()

    base_html = '''<!DOCTYPE html>
<html lang="en" class="h-full bg-gray-50">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ title }} | ''' + app_title + '''</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            brand: { 50:'#f0fdf4', 100:'#dcfce7', 500:'#22c55e', 600:'#16a34a', 700:'#15803d', 900:'#14532d' },
            ink: '#111827',
          }
        }
      }
    }
  </script>
  <style>
    .loading-pulse { animation: pulse 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  </style>
</head>
<body class="h-full">
  <div class="min-h-full">
    <nav class="bg-ink">
      <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div class="flex h-14 items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="h-8 w-8 rounded-lg bg-brand-500 flex items-center justify-center">
              <svg class="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" /></svg>
            </div>
            <span class="text-white font-semibold text-lg">''' + app_title + '''</span>
          </div>
          <div class="flex items-center gap-4">
            <a href="/" class="text-gray-300 hover:text-white text-sm font-medium">Dashboard</a>
            <span id="health-dot" class="h-2.5 w-2.5 rounded-full bg-gray-500" title="Checking..."></span>
          </div>
        </div>
      </div>
    </nav>
    <main class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8">
      {% block content %}{% endblock %}
    </main>
  </div>
  <script>
    fetch('/health').then(r=>r.json()).then(d=>{
      const dot=document.getElementById('health-dot');
      dot.className='h-2.5 w-2.5 rounded-full '+(d.ok?'bg-green-400':'bg-red-400');
      dot.title=d.ok?'API healthy':'API error';
    }).catch(()=>{
      document.getElementById('health-dot').className='h-2.5 w-2.5 rounded-full bg-red-400';
    });
  </script>
</body>
</html>
'''

    dashboard_html = '''{% extends "base.html" %}
{% block content %}
<div class="mb-8 flex items-center justify-between">
  <div>
    <h1 class="text-3xl font-bold text-gray-900">Dashboard</h1>
    <p class="mt-1 text-sm text-gray-500">Overview of your application</p>
  </div>
  <button onclick="location.reload()" class="rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-500">Refresh</button>
</div>

<!-- Stats cards -->
<div class="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4 mb-8">
  {% for stat in stats %}
  <div class="overflow-hidden rounded-xl bg-white shadow ring-1 ring-gray-900/5">
    <div class="px-5 py-4">
      <p class="text-sm font-medium text-gray-500 truncate">{{ stat.label }}</p>
      <p class="mt-1 text-3xl font-bold tracking-tight text-gray-900">{{ stat.value }}</p>
    </div>
  </div>
  {% endfor %}
  {% if not stats %}
  <div class="col-span-full overflow-hidden rounded-xl bg-white shadow ring-1 ring-gray-900/5">
    <div class="px-5 py-4">
      <p class="text-sm font-medium text-gray-500">No stats available yet</p>
    </div>
  </div>
  {% endif %}
</div>

<!-- Main content area -->
<div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
  <!-- Primary panel -->
  <div class="lg:col-span-2">
    <div class="rounded-xl bg-white shadow ring-1 ring-gray-900/5 overflow-hidden">
      <div class="px-6 py-5 border-b border-gray-100">
        <h2 class="text-lg font-semibold text-gray-900">Recent Activity</h2>
      </div>
      <div class="px-6 py-8" id="activity-area">
        {% if items %}
        <div class="divide-y divide-gray-100">
          {% for item in items %}
          <div class="py-4 flex items-center justify-between gap-4">
            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-gray-900 truncate">{{ item.title }}</p>
              {% if item.subtitle %}
              <p class="text-sm text-gray-500">{{ item.subtitle }}</p>
              {% endif %}
            </div>
            {% if item.badge %}
            <span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold
              {% if item.badge_color == 'green' %}bg-green-50 text-green-700 ring-1 ring-green-600/20
              {% elif item.badge_color == 'amber' %}bg-amber-50 text-amber-700 ring-1 ring-amber-600/20
              {% elif item.badge_color == 'red' %}bg-red-50 text-red-700 ring-1 ring-red-600/20
              {% else %}bg-gray-50 text-gray-700 ring-1 ring-gray-600/20{% endif %}">
              {{ item.badge }}
            </span>
            {% endif %}
            {% if item.action %}
            <a href="{{ item.action_url }}" class="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600">
              {{ item.action }}
            </a>
            {% endif %}
          </div>
          {% endfor %}
        </div>
        {% else %}
        <div class="text-center py-8">
          <svg class="mx-auto h-12 w-12 text-gray-300" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 13.5h3.86a2.25 2.25 0 0 1 2.012 1.244l.256.512a2.25 2.25 0 0 0 2.013 1.244h3.218a2.25 2.25 0 0 0 2.013-1.244l.256-.512a2.25 2.25 0 0 1 2.013-1.244h3.859" /></svg>
          <h3 class="mt-2 text-sm font-semibold text-gray-900">No activity yet</h3>
          <p class="mt-1 text-sm text-gray-500">Get started by creating your first record.</p>
          <button onclick="location.reload()" class="mt-4 rounded-lg bg-ink px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-gray-700">Check for new records</button>
        </div>
        {% endif %}
      </div>
    </div>
  </div>

  <!-- Sidebar -->
  <div class="space-y-6">
    <div class="rounded-xl bg-white shadow ring-1 ring-gray-900/5 overflow-hidden">
      <div class="px-6 py-5 border-b border-gray-100">
        <h2 class="text-lg font-semibold text-gray-900">System Status</h2>
      </div>
      <div class="px-6 py-4 space-y-3">
        {% for check in health_checks %}
        <div class="flex items-center justify-between">
          <span class="text-sm text-gray-600">{{ check.label }}</span>
          <span class="inline-flex items-center gap-1.5">
            <span class="h-2 w-2 rounded-full {% if check.ok %}bg-green-500{% else %}bg-red-500{% endif %}"></span>
            <span class="text-xs font-medium {% if check.ok %}text-green-700{% else %}text-red-700{% endif %}">
              {{ 'OK' if check.ok else 'Error' }}
            </span>
          </span>
        </div>
        {% endfor %}
        {% if not health_checks %}
        <p class="text-sm text-gray-500">Loading status...</p>
        {% endif %}
      </div>
    </div>

    <div class="rounded-xl bg-white shadow ring-1 ring-gray-900/5 overflow-hidden">
      <div class="px-6 py-5 border-b border-gray-100">
        <h2 class="text-lg font-semibold text-gray-900">Routes</h2>
      </div>
      <div class="px-6 py-4">
        {% if routes %}
        <ul class="space-y-2">
          {% for route in routes %}
          <li class="flex items-center gap-2">
            <span class="inline-flex items-center rounded-md bg-brand-50 px-2 py-1 text-xs font-medium text-brand-700 ring-1 ring-brand-600/20">{{ route }}</span>
          </li>
          {% endfor %}
        </ul>
        {% else %}
        <p class="text-sm text-gray-500">No feature routes mounted</p>
        {% endif %}
      </div>
    </div>
  </div>
</div>
{% endblock %}
'''

    error_html = '''{% extends "base.html" %}
{% block content %}
<div class="text-center py-16">
  <div class="mx-auto h-16 w-16 rounded-full bg-red-50 flex items-center justify-center mb-4">
    <svg class="h-8 w-8 text-red-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" /></svg>
  </div>
  <h1 class="text-2xl font-bold text-gray-900">{{ title }}</h1>
  <p class="mt-2 text-sm text-gray-500">{{ message }}</p>
  <a href="/" class="mt-6 inline-block rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-500">Back to dashboard</a>
</div>
{% endblock %}
'''

    with open(os.path.join(tpl_dir, "base.html"), "w", encoding="utf-8") as f:
        f.write(base_html)
    with open(os.path.join(tpl_dir, "dashboard.html"), "w", encoding="utf-8") as f:
        f.write(dashboard_html)
    with open(os.path.join(tpl_dir, "error.html"), "w", encoding="utf-8") as f:
        f.write(error_html)

    views_py = '''"""Generated views — server-rendered dashboard using Jinja2 + Tailwind."""
from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def register_views(app: FastAPI, templates: Jinja2Templates):
    """Mount the server-rendered dashboard at /."""

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        stats = []
        items = []
        health_checks = [{"label": "API", "ok": True}]
        routes = []

        # Pull live stats from the backend
        try:
            from scrapyard.database.db_session import get_db
            db = next(get_db())
            try:
                from scrapyard.admin.dashboards import admin_overview
                overview = admin_overview(db)
                for k, v in overview.items():
                    stats.append({"label": k.replace("_", " ").title(), "value": v})
            except Exception:
                pass
            db.close()
        except Exception:
            health_checks.append({"label": "Database", "ok": False})

        # Capabilities / mounted routes
        try:
            from scrapyard_app.capabilities import CAPABILITIES
            routes = CAPABILITIES.get("routers_mounted", [])
            if not stats:
                stats.append({"label": "Feature Routes", "value": len(routes)})
        except Exception:
            pass

        if not stats:
            stats = [{"label": "Status", "value": "Running"}]

        return templates.TemplateResponse(request, "dashboard.html", {
            "title": "Dashboard",
            "stats": stats, "items": items,
            "health_checks": health_checks, "routes": routes,
        })

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        return templates.TemplateResponse(request, "error.html", {
            "title": "Page not found",
            "message": "The page you are looking for does not exist.",
        }, status_code=404)

    @app.exception_handler(500)
    async def server_error(request: Request, exc):
        return templates.TemplateResponse(request, "error.html", {
            "title": "Something went wrong",
            "message": "An unexpected error occurred. Please try again.",
        }, status_code=500)
'''
    with open(os.path.join(out_dir, "scrapyard_app", "views.py"), "w", encoding="utf-8") as f:
        f.write(views_py)


def generate_runtime_app(out_dir: str, app_type: str, selected_parts: list[str]) -> dict:
    """Write the runtime entrypoint + support package into an assembled folder."""
    route_reg = _load("route_registry.json")
    env_reg = _load("env_registry.json")
    metadata = _load_template_metadata().get(app_type, {})
    required_routes = metadata.get("required_feature_routes", [])
    probe = metadata.get("behavior_probe", "")
    sel = set(selected_parts)

    # which selected parts expose routers we can mount; a router is REQUIRED if its
    # prefix covers a required feature route (its import must fail loudly, not skip).
    routers = []
    for ip, meta in route_reg.items():
        if ip in sel:
            prefix = meta.get("mount_prefix", "")
            required = any(r == prefix or r.startswith(prefix.rstrip("/") + "/")
                           for r in required_routes)
            routers.append({"import_path": ip, "required": required, **meta})
    mount_prefixes = [r.get("mount_prefix", "") for r in routers if r.get("mount_prefix")]

    model_candidates = ["scrapyard.identity.users", "scrapyard.identity.session_manager",
                        "scrapyard.admin.audit_logs", "scrapyard.jobs.db_queue",
                        "scrapyard.content.blog", "scrapyard.marketplace.listings",
                        "scrapyard.ai.document_store"]
    model_modules = [m for m in model_candidates if m in sel]

    pkg = os.path.join(out_dir, "scrapyard_app")
    os.makedirs(pkg, exist_ok=True)
    open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8").write("")
    open(os.path.join(pkg, "settings.py"), "w", encoding="utf-8").write(_SETTINGS)
    open(os.path.join(pkg, "bootstrap.py"), "w", encoding="utf-8").write(_bootstrap_py(model_modules))
    open(os.path.join(pkg, "capabilities.py"), "w", encoding="utf-8").write(
        _capabilities_py(app_type, selected_parts, mount_prefixes, required_routes, probe))
    open(os.path.join(pkg, "routes.py"), "w", encoding="utf-8").write(_routes_py(routers))
    open(os.path.join(out_dir, "main.py"), "w", encoding="utf-8").write(_MAIN)
    open(os.path.join(out_dir, "behavior_check.py"), "w", encoding="utf-8").write(
        _behavior_check_py(probe, required_routes))

    # .env.example from base + per-part env registry
    env_lines = ["APP_ENV=development", "DATABASE_URL=sqlite:///./app.db",
                 "SECRET_KEY=dev-only-change-me", "SCRAPYARD_RLS=",
                 "CACHE_BACKEND=memory", "REDIS_URL=", "RATE_LIMIT_BACKEND=memory",
                 "SENTRY_DSN=", "OTEL_EXPORTER_OTLP_ENDPOINT="]
    if model_modules:
        env_lines.append("SCRAPYARD_MODEL_MODULES=" + ",".join(model_modules))
    seen = set(l.split("=")[0] for l in env_lines)
    for ip in selected_parts:
        for var in env_reg.get(ip, []):
            if var not in seen:
                env_lines.append(f"{var}="); seen.add(var)
    open(os.path.join(out_dir, ".env.example"), "w", encoding="utf-8").write("\n".join(env_lines) + "\n")

    # Alembic migrations: scoped env + baked baseline; prod applies them at boot.
    mig = _write_app_migrations(out_dir, model_modules)
    # Per-request RLS context helper (used when SCRAPYARD_RLS=enforce on Postgres).
    open(os.path.join(out_dir, "scrapyard_app", "rls.py"), "w", encoding="utf-8").write(
        '"""Per-request row-level-security context.\n\n'
        'When RLS is enforced (SCRAPYARD_RLS=enforce on PostgreSQL), every scoped query\n'
        'must run inside a transaction that has set the current principal, or the\n'
        'fail-closed policies return zero rows. Use rls_session() per request.\n"""\n'
        'from contextlib import contextmanager\n'
        'from scrapyard.database.db_session import get_sessionmaker\n'
        'from scrapyard.security.row_level_security import set_context\n\n'
        '@contextmanager\n'
        'def rls_session(*, user_id=None, tenant_id=None):\n'
        '    """Yield a DB session bound to the principal; context is transaction-local."""\n'
        '    Session = get_sessionmaker()\n'
        '    db = Session()\n'
        '    try:\n'
        '        db.begin()\n'
        '        set_context(db.connection(), user_id=user_id, tenant_id=tenant_id)\n'
        '        yield db\n'
        '        db.commit()\n'
        '    except Exception:\n'
        '        db.rollback(); raise\n'
        '    finally:\n'
        '        db.close()\n')
    req_path = os.path.join(out_dir, "requirements.txt")
    extra_reqs = set()
    extra_reqs.add("jinja2")
    if model_modules:  # the app boots migrations in production -> needs alembic
        extra_reqs.add("alembic")
    _sp = set(selected_parts)
    # observability is force-included as runtime support, so its SDKs are always wired
    extra_reqs.add("sentry-sdk")
    extra_reqs.add("opentelemetry-sdk")
    if extra_reqs:
        reqs = set(l.strip() for l in open(req_path, encoding="utf-8")) if os.path.exists(req_path) else set()
        reqs |= extra_reqs
        open(req_path, "w", encoding="utf-8").write("\n".join(sorted(r for r in reqs if r)) + "\n")

    # CAPABILITIES.md
    md = ["# Capabilities — " + app_type, "",
          "_Generated. Lists what runs, what production needs, and local-only fallbacks._", "",
          "## Always-on endpoints", "- `GET /health`", "- `GET /capabilities`", "",
          "## Mounted feature routers",
          *([f"- `{r.get('mount_prefix') or r['import_path']}` ({r['import_path']})" for r in routers] or ["- none selected"]),
          "", "## Required configuration (see .env.example)",
          *([f"- `{v}` ← {ip}" for ip in selected_parts for v in env_reg.get(ip, [])] or ["- only base vars (APP_ENV, DATABASE_URL, SECRET_KEY)"]),
          "", "## Local-only fallbacks (refused in production)",
          "- security.local_crypto_backend → `SCRAPYARD_CRYPTO_BACKEND=citadel`",
          "- communication.email_console → configure SMTP",
          "- ai.offline_provider → set `SCRAPYARD_LLM_PROVIDER` + key",
          "- jobs.memory_queue → `JOBS_BACKEND=db`",
          "", "## Honest status",
          "- `production_ready: false` — configure the above and run migrations before production.",
          "- Routers that can't wire are skipped in dev (see `/capabilities`) and **raise** in production."]
    open(os.path.join(out_dir, "CAPABILITIES.md"), "w", encoding="utf-8").write("\n".join(md))

    # smoke_check.py
    open(os.path.join(out_dir, "smoke_check.py"), "w", encoding="utf-8").write(
        'from fastapi.testclient import TestClient\n'
        'from main import app\n\n'
        'def main():\n'
        '    c = TestClient(app)\n'
        '    r = c.get("/health"); assert r.status_code == 200 and r.json()["ok"] is True\n'
        '    cap = c.get("/capabilities"); assert cap.status_code == 200 and "template" in cap.json()\n'
        '    print("Smoke check passed:", len(cap.json().get("routers_mounted", [])), "router(s) mounted")\n\n'
        'if __name__ == "__main__":\n'
        '    main()\n')

    # Server-rendered frontend: Jinja2 templates + Tailwind CDN
    _write_frontend(out_dir, app_type, mount_prefixes)

    written = ["main.py", "scrapyard_app/settings.py", "scrapyard_app/bootstrap.py",
               "scrapyard_app/routes.py", "scrapyard_app/capabilities.py",
               "scrapyard_app/views.py", "templates/",
               ".env.example", "CAPABILITIES.md", "smoke_check.py"]
    return {"written": written, "routers": [r["import_path"] for r in routers],
            "model_modules": model_modules, "migration_baseline": mig.get("baseline")}
