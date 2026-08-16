"""
dashboards — Admin overview metrics aggregation.

### PART-META-JSON
{
  "name": "dashboards",
  "layer": "admin",
  "purpose": "Admin overview metrics aggregation.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: get_admin_overview(db, org_id); register_dashboard_metric(metric_name, metric_source, description); unregister_dashboard_metric(metric_name); configure_dashboard(db, config); bulk_refresh_dashboard(db); DashboardConfig(...); MetricDetails(...); AdminDashboard(...) (plus more).",
  "outputs": "Returns: get_admin_overview -> AdminDashboard; register_dashboard_metric -> None; unregister_dashboard_metric -> None; configure_dashboard -> DashboardConfig; bulk_refresh_dashboard -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Renders HTML with all caller text escaped via html.escape (XSS-safe); any HTML 'slot' arguments are inserted verbatim and must be pre-escaped by the caller. Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `get_admin_overview` from `scrapyard.admin.dashboards` and call it as shown in `example`; run `py -m scrapyard.admin.dashboards` to see its offline selftest.",
  "example": "from scrapyard.admin.dashboards import get_admin_overview",
  "import_path": "scrapyard.admin.dashboards"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
import html
from typing import Any, Dict, List, Optional, Callable
from sqlalchemy.orm import Session
from pydantic import BaseModel
from sqlalchemy import select, func
from cryptography.fernet import Fernet

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class DashboardConfig(BaseModel):
    metrics_to_include: List[str] = []
    default_filters: Dict[str, Any] = {}
    audit_level: str = "basic"

class MetricDetails(BaseModel):
    source: str
    description: str
    last_update_time: int

class AdminDashboard(BaseModel):
    users: int
    active_subscriptions: int

class DashboardPolicy(BaseModel):
    access_control: Dict[str, Any] = {}
    rate_limiting: Dict[str, Any] = {}
    data_masking: Dict[str, Any] = {}

class MetricNotFoundError(Exception):
    pass

class DashboardConfigError(Exception):
    pass

class AuditLogError(Exception):
    pass

class DashboardRefreshError(Exception):
    pass

class PolicyViolationError(Exception):
    pass

class SerializationError(Exception):
    pass

class DependencyNotFoundError(Exception):
    pass

class MetricProcessingError(Exception):
    pass

def get_admin_overview(db: Session, org_id: Optional[int] = None) -> AdminDashboard:
    dashboard = AdminDashboard(users=0, active_subscriptions=0)
    try:
        from scrapyard.admin.user_management import user_count
        # user_count is org-agnostic (User carries no org column).
        dashboard.users = user_count(db)
    except DependencyNotFoundError as e:
        raise e
    try:
        from scrapyard.billing.subscriptions import Subscription
        query = select(func.count()).select_from(Subscription).where(Subscription.status == "active")
        if org_id is not None:
            query = query.where(Subscription.org_id == org_id)
        dashboard.active_subscriptions = db.scalar(query) or 0
    except Exception:
        # Billing tables absent in this deployment: degrade to 0, not a 500.
        dashboard.active_subscriptions = 0
    return dashboard

# ---------------------------------------------------------------------------
# Metric registry, configuration, policy (real implementations)
# ---------------------------------------------------------------------------

import json as _json
import time as _time

_metric_registry: Dict[str, Dict[str, Any]] = {}
_dashboard_config: DashboardConfig = DashboardConfig()
_dashboard_policy: DashboardPolicy = DashboardPolicy()
_dashboard_audit: List[Dict[str, Any]] = []


def register_dashboard_metric(metric_name: str, metric_source: Callable[[Session], Any],
                              description: str = "") -> None:
    """Register a named metric backed by a callable(db) -> value."""
    if not metric_name or not isinstance(metric_name, str):
        raise DashboardConfigError("metric_name must be a non-empty string")
    if not callable(metric_source):
        raise DashboardConfigError("metric_source must be callable")
    _metric_registry[metric_name] = {
        "source": metric_source,
        "description": description or f"metric {metric_name}",
        "value": None,
        "last_update_time": 0,
    }


def unregister_dashboard_metric(metric_name: str) -> None:
    _metric_registry.pop(metric_name, None)


def configure_dashboard(db: Session, config: DashboardConfig) -> DashboardConfig:
    """Validate and store the active dashboard configuration."""
    if config.audit_level not in ("off", "basic", "detailed"):
        raise DashboardConfigError(f"unknown audit_level: {config.audit_level!r}")
    unknown = [m for m in config.metrics_to_include if m not in _metric_registry]
    if unknown:
        raise MetricNotFoundError(f"unregistered metrics in config: {unknown}")
    global _dashboard_config
    _dashboard_config = config
    audit_dashboard_change({"event": "configure", "metrics": list(config.metrics_to_include),
                            "audit_level": config.audit_level})
    return _dashboard_config


def bulk_refresh_dashboard(db: Session) -> Dict[str, Any]:
    """Evaluate every registered metric source and cache the values."""
    refreshed: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for name, entry in _metric_registry.items():
        try:
            value = entry["source"](db)
        except Exception as e:  # noqa: BLE001 - one bad metric must not kill the refresh
            errors[name] = f"{type(e).__name__}: {e}"
            continue
        entry["value"] = value
        entry["last_update_time"] = int(_time.time())
        refreshed[name] = value
    if errors:
        audit_dashboard_change({"event": "refresh_errors", "errors": errors})
    else:
        audit_dashboard_change({"event": "refresh", "metrics": list(refreshed.keys())})
    if errors and not refreshed:
        raise DashboardRefreshError(f"all metrics failed: {errors}")
    return {"refreshed": refreshed, "errors": errors}


def get_metric_details(metric_name: str) -> MetricDetails:
    entry = _metric_registry.get(metric_name)
    if entry is None:
        raise MetricNotFoundError(f"metric {metric_name!r} is not registered")
    return MetricDetails(source=getattr(entry["source"], "__name__", repr(entry["source"])),
                         description=entry["description"],
                         last_update_time=entry["last_update_time"])


def get_metric_value(metric_name: str) -> Any:
    entry = _metric_registry.get(metric_name)
    if entry is None:
        raise MetricNotFoundError(f"metric {metric_name!r} is not registered")
    return entry["value"]


def audit_dashboard_change(event_data: Dict[str, Any]) -> None:
    """Record a dashboard change event in the in-process audit trail."""
    if not isinstance(event_data, dict) or not event_data:
        raise AuditLogError("event_data must be a non-empty dict")
    if _dashboard_config.audit_level == "off":
        return
    entry = dict(event_data)
    entry["at"] = int(_time.time())
    _dashboard_audit.append(entry)


def get_dashboard_audit() -> List[Dict[str, Any]]:
    return list(_dashboard_audit)


def generate_dashboard_report(db: Session, filters: Dict[str, Any],
                              time_range: Dict[str, Any]) -> str:
    """Refresh and render the selected metrics as a JSON report string."""
    bulk_refresh_dashboard(db)
    wanted = filters.get("metrics") if filters else None
    selected = {}
    for name, entry in _metric_registry.items():
        if wanted is not None and name not in wanted:
            continue
        if _dashboard_config.metrics_to_include and name not in _dashboard_config.metrics_to_include:
            continue
        selected[name] = {"value": entry["value"],
                          "last_update_time": entry["last_update_time"]}
    report = {"generated_at": int(_time.time()), "time_range": time_range or {},
              "metrics": selected}
    try:
        return _json.dumps(report, default=str)
    except (TypeError, ValueError) as e:
        raise SerializationError(str(e)) from e


def set_dashboard_policy(policy: DashboardPolicy) -> DashboardPolicy:
    if not isinstance(policy, DashboardPolicy):
        raise PolicyViolationError("policy must be a DashboardPolicy")
    global _dashboard_policy
    _dashboard_policy = policy
    audit_dashboard_change({"event": "policy_change"})
    return _dashboard_policy


def get_dashboard_policy() -> DashboardPolicy:
    return _dashboard_policy

def serialize_dashboard(dashboard_data: AdminDashboard) -> str:
    return dashboard_data.model_dump_json()

def decrypt_secret(secret_key: str, encrypted_secret: str) -> str:
    fernet = Fernet(secret_key.encode())
    decrypted = fernet.decrypt(encrypted_secret.encode()).decode()
    return decrypted

def clean_html(html_content: str) -> str:
    return html.escape(html_content)

def load_dashboard_template(template_name: str, **kwargs) -> str:
    env = Environment(loader=FileSystemLoader('templates'))
    template = env.get_template(template_name)
    return template.render(**kwargs)

def admin_overview(db) -> dict:
    """Aggregate counts for an admin dashboard from whatever models exist."""
    out={}
    try:
        from scrapyard.admin.user_management import user_count
        out["users"]=user_count(db)
    except Exception: pass
    try:
        from scrapyard.billing.subscriptions import Subscription
        from sqlalchemy import select, func
        out["active_subscriptions"]=db.scalar(select(func.count()).select_from(Subscription)
            .where(Subscription.status=="active")) or 0
    except Exception: pass
    return out


def _selftest() -> None:
    """Offline self-test: registry, config, refresh, report, overview."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from scrapyard.database.base_model import Base
    from scrapyard.identity.users import User
    import scrapyard.admin.audit_logs  # noqa: F401

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                db.add_all([User(email="x@example.com", password_hash="h"),
                            User(email="y@example.com", password_hash="h")])
                db.commit()

                # Overview counts real users
                overview = get_admin_overview(db)
                assert overview.users == 2
                assert "users" in serialize_dashboard(overview)
                assert admin_overview(db)["users"] == 2

                # Metric registry round-trip
                register_dashboard_metric("user_total",
                                          lambda s: s.scalar(select(func.count()).select_from(User)),
                                          description="total users")
                try:
                    register_dashboard_metric("bad", "not-callable")
                    raise AssertionError("expected DashboardConfigError")
                except DashboardConfigError:
                    pass
                try:
                    get_metric_details("missing")
                    raise AssertionError("expected MetricNotFoundError")
                except MetricNotFoundError:
                    pass

                out = bulk_refresh_dashboard(db)
                assert out["refreshed"]["user_total"] == 2 and not out["errors"]
                assert get_metric_value("user_total") == 2
                details = get_metric_details("user_total")
                assert details.description == "total users" and details.last_update_time > 0

                # A failing metric is reported, not fatal
                register_dashboard_metric("broken", lambda s: 1 / 0)
                out = bulk_refresh_dashboard(db)
                assert "broken" in out["errors"] and out["refreshed"]["user_total"] == 2
                unregister_dashboard_metric("broken")

                # Config validation
                cfg = configure_dashboard(db, DashboardConfig(metrics_to_include=["user_total"],
                                                              audit_level="basic"))
                assert cfg.metrics_to_include == ["user_total"]
                try:
                    configure_dashboard(db, DashboardConfig(audit_level="verbose"))
                    raise AssertionError("expected DashboardConfigError")
                except DashboardConfigError:
                    pass
                try:
                    configure_dashboard(db, DashboardConfig(metrics_to_include=["ghost"]))
                    raise AssertionError("expected MetricNotFoundError")
                except MetricNotFoundError:
                    pass

                # Report generation over the selected metrics
                import json
                report = json.loads(generate_dashboard_report(db, {"metrics": ["user_total"]},
                                                              {"days": 7}))
                assert report["metrics"]["user_total"]["value"] == 2
                assert report["time_range"] == {"days": 7}

                # Policy storage
                pol = set_dashboard_policy(DashboardPolicy(access_control={"role": "admin"}))
                assert get_dashboard_policy().access_control == {"role": "admin"}
                try:
                    set_dashboard_policy("nope")
                    raise AssertionError("expected PolicyViolationError")
                except PolicyViolationError:
                    pass

                # Audit trail captured events
                events = {e["event"] for e in get_dashboard_audit()}
                assert {"configure", "refresh", "policy_change"} <= events

                # Helpers
                assert clean_html("<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;"
        finally:
            engine.dispose()
    print("dashboards self-test passed")


if __name__ == "__main__":
    _selftest()
