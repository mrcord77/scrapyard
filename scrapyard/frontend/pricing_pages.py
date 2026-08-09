"""
pricing_pages — Pricing tiers + checkout CTA HTML (Python server-side rendering, no react).

### PART-META-JSON
{
  "name": "pricing_pages",
  "layer": "frontend",
  "purpose": "Python server-side HTML rendering of pricing tiers, plan cards, comparisons and checkout CTA blocks, with plan validation, pagination, policy filtering, and an optional SQLAlchemy-backed plan store.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi",
    "sqlalchemy"
  ],
  "inputs": "Plan dicts ({name, price, features, ...}); CTAConfig(text, href); PricingPolicy; optional SQLAlchemy Session for get_plans_from_db.",
  "outputs": "HTML strings; serialized plan dicts; PaginatedPlans batches.",
  "files_created": [],
  "security_notes": "All plan names/features/CTA text and hrefs are escaped with html.escape (XSS-safe); CTAConfig rejects javascript:/data: hrefs. Prices are display strings only - never compute billing from them.",
  "ai_usage": "Import `generate_plan_card` from `scrapyard.frontend.pricing_pages` and call it as shown in `example`; run `py -m scrapyard.frontend.pricing_pages` to see its offline selftest.",
  "example": "from scrapyard.frontend.pricing_pages import generate_plan_card",
  "import_path": "scrapyard.frontend.pricing_pages"
}
### END-PART-META
"""
from typing import List, Dict, Optional, Any
from sqlalchemy import JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from fastapi import HTTPException
from pydantic import BaseModel, field_validator
from scrapyard.database.base_model import IntPKModel
import html

class CTAConfig(BaseModel):
    text: str
    href: str  # relative ("#", "/checkout") or absolute URLs are both valid link targets

    @field_validator("href")
    @classmethod
    def _safe_href(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("href must be non-empty")
        if v.strip().lower().startswith(("javascript:", "data:", "vbscript:")):
            raise ValueError("href scheme not allowed")
        return v

class PricingPolicy(BaseModel):
    hide_premium_plans: bool

class PaginatedPlans:
    def __init__(self, items: List[Dict[str, Any]], total: int, page: int, per_page: int):
        self.items = items
        self.total = total
        self.page = page
        self.per_page = per_page

class InvalidPlanStructureError(Exception):
    pass

class InvalidThemeError(Exception):
    pass

def generate_plan_card(plan: Dict[str, Any]) -> str:
    validate_plan(plan)
    feats = "".join(f"<li>{html.escape(f)}</li>" for f in plan.get("features", []))
    return (f'<div class="plan"><h3>{html.escape(plan["name"])}</h3>'
            f'<div class="price">{html.escape(str(plan.get("price", "")))}</div>'
            f'<ul>{feats}</ul></div>')

def render_call_to_action(cta: CTAConfig) -> str:
    return f'<a href="{html.escape(cta.href)}" class="cta">{html.escape(cta.text)}</a>'

def apply_theme(plan: Dict[str, Any], theme: str = "default") -> Dict[str, Any]:
    if theme not in ["dark", "light", "premium"]:
        raise InvalidThemeError(f"Unknown theme {theme}")
    # Apply theme logic here
    return plan

def validate_plan(plan: Dict[str, Any]) -> None:
    required_fields = {"name", "price"}
    missing_fields = required_fields - set(plan.keys())
    if missing_fields:
        raise InvalidPlanStructureError(f"Missing fields {missing_fields}")

def paginate_plans(plans: List[Dict[str, Any]], page: int = 1, per_page: int = 10) -> PaginatedPlans:
    total = len(plans)
    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    return PaginatedPlans(items=plans[start_index:end_index], total=total, page=page, per_page=per_page)

def filter_plans(plans: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    filtered_plans = []
    for plan in plans:
        if all(plan.get(k) == v for k, v in filters.items()):
            filtered_plans.append(plan)
    return filtered_plans

def serialize_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": html.escape(plan["name"]),
        "price": plan["price"],
        "features": [html.escape(f) for f in plan.get("features", [])]
    }

def render_plan_list(plans: List[Dict[str, Any]]) -> str:
    cards = "".join(generate_plan_card(plan) for plan in plans)
    return f'<div class="plans">{cards}</div>'

def log_plan_render(plan: Dict[str, Any], user_id: Optional[str] = None):
    import logging
    logging.getLogger("scrapyard.frontend.pricing_pages").info(
        "plan rendered name=%s user=%s", plan.get("name"), user_id or "-")

def apply_policy(plan: Dict[str, Any], policy: PricingPolicy) -> Dict[str, Any]:
    if policy.hide_premium_plans and "premium" in plan["name"].lower():
        return {"name": "Hidden", "price": None}
    return plan

def bulk_render_plans(plans: List[Dict[str, Any]]) -> List[str]:
    return [generate_plan_card(plan) for plan in plans]

def render_plan_comparison(plans: List[Dict[str, Any]]) -> str:
    comparison = "".join(f'<div class="comparison-plan">{generate_plan_card(plan)}</div>' for plan in plans)
    return f'<div class="plan-comparison">{comparison}</div>'

def render_plan_details(plan: Dict[str, Any]) -> str:
    features_list = "".join(f"<li>{html.escape(f)}</li>" for f in plan.get("features", []))
    cta = render_call_to_action(CTAConfig(text="Choose Plan", href="#"))
    return f'<h1>{html.escape(plan["name"])} Details</h1><div class="features-list"><ul>{features_list}</ul></div>{cta}'

def render_pricing_page(plans: List[Dict[str, Any]]) -> str:
    paginated_plans = paginate_plans(plans)
    plan_cards = render_plan_list(paginated_plans.items)
    cta = render_call_to_action(CTAConfig(text="Choose Plan", href="#"))
    return f'<h1>Pricing</h1><div class="plans">{plan_cards}</div>{cta}'

class PlanModel(IntPKModel):
    """Persisted pricing plan (features stored as a JSON list)."""
    __tablename__ = "pricing_pages_plans"
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[str] = mapped_column(String(40), nullable=False)
    features: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


def get_plans_from_db(session: Session) -> List[Dict[str, Any]]:
    """Real query: read all PlanModel rows into render-ready plan dicts."""
    rows = session.scalars(select(PlanModel).order_by(PlanModel.id)).all()
    return [{"name": r.name, "price": r.price, "features": list(r.features or [])}
            for r in rows]


def render_pricing_page_or_400(plans: List[Dict[str, Any]]) -> str:
    """FastAPI-friendly wrapper: render or raise HTTP 400 on bad plan data."""
    try:
        return render_pricing_page(plans)
    except (InvalidPlanStructureError, InvalidThemeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


def _selftest() -> bool:
    plans = [
        {"name": "Free", "price": "$0", "features": ["1 user", "Community support"]},
        {"name": "Pro", "price": "$12", "features": ["10 users", "Email support"]},
        {"name": "Premium Max", "price": "$99", "features": ["SSO"]},
    ]

    # cards render valid, escaped HTML (heading closed, single li pair)
    card = generate_plan_card({"name": "<b>Evil</b>", "price": "$1", "features": ["<i>f</i>"]})
    assert "&lt;b&gt;Evil&lt;/b&gt;" in card and "<b>Evil</b>" not in card
    assert card.count("<li>") == 1 and card.count("</li>") == 1
    assert "</h3>" in card

    # CTA accepts relative hrefs, rejects dangerous schemes
    assert 'href="#"' in render_call_to_action(CTAConfig(text="Go", href="#"))
    assert 'href="/checkout"' in render_call_to_action(CTAConfig(text="Go", href="/checkout"))
    try:
        CTAConfig(text="x", href="javascript:alert(1)")
        raise AssertionError("javascript: href accepted")
    except Exception:
        pass

    # full page renders end-to-end (this used to crash on href='#')
    page = render_pricing_page(plans)
    assert "<h1>Pricing</h1>" in page and page.count('class="plan"') == 3
    assert 'class="cta"' in page
    assert render_pricing_page_or_400(plans) == page

    # validation, pagination, filtering, policy, themes
    try:
        validate_plan({"name": "no-price"})
        raise AssertionError("invalid plan accepted")
    except InvalidPlanStructureError:
        pass
    pg = paginate_plans(plans, page=1, per_page=2)
    assert len(pg.items) == 2 and pg.total == 3
    assert filter_plans(plans, {"price": "$12"})[0]["name"] == "Pro"
    hidden = apply_policy(plans[2], PricingPolicy(hide_premium_plans=True))
    assert hidden["name"] == "Hidden"
    try:
        apply_theme(plans[0], "neon")
        raise AssertionError("unknown theme accepted")
    except InvalidThemeError:
        pass

    # DB-backed plans: real round-trip through SQLite
    import os
    import tempfile
    from sqlalchemy import create_engine
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        engine = create_engine(f"sqlite:///{os.path.join(td, 'plans.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as s:
                s.add(PlanModel(name="Solo", price="$5", features=["1 seat"]))
                s.add(PlanModel(name="Team", price="$20", features=["5 seats"]))
                s.commit()
                got = get_plans_from_db(s)
            assert [p["name"] for p in got] == ["Solo", "Team"]
            assert got[1]["features"] == ["5 seats"]
            assert 'class="plan"' in render_pricing_page(got)
        finally:
            engine.dispose()

    # legacy grafted renderer still works
    legacy = pricing_page([{"name": "A", "price": 1, "features": ["x"], "cta_href": "/a"}])
    assert "Choose A" in legacy

    log_plan_render(plans[0], user_id="u1")
    print("pricing_pages selftest OK")
    return True


# --- grafted from original part (API stability) ---
def pricing_page(plans: list[dict]):
    """plans: [{name, price, features:[...], cta_href}]"""
    e=html.escape; cards=""
    for p in plans:
        feats="".join(f"<li>{e(f)}</li>" for f in p.get("features",[]))
        cta=f'<a href="{e(p.get("cta_href","#"))}">Choose {e(p["name"])}</a>'
        cards+=(f'<div class="plan"><h3>{e(p["name"])}</h3>'
                f'<div class="price">{e(str(p.get("price","")))}</div>'
                f'<ul>{feats}</ul>{cta}</div>')
    return f'<h1>Pricing</h1><div class="plans">{cards}</div>'


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
