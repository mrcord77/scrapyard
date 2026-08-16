"""
entitlements — Map plan -> entitlements/limits.

### PART-META-JSON
{
  "name": "entitlements",
  "layer": "billing",
  "purpose": "Map plan -> entitlements/limits.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: default_entitlements(); feature_allowed(subscription, feature, plans).",
  "outputs": "Returns: default_entitlements -> Entitlements; feature_allowed -> bool.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `default_entitlements` from `scrapyard.billing.entitlements` and call it as shown in `example`; run `py -m scrapyard.billing.entitlements` to see its offline selftest.",
  "example": "from scrapyard.billing.entitlements import default_entitlements",
  "import_path": "scrapyard.billing.entitlements"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
from scrapyard.authorization.entitlement_gate import Plan, Entitlements

# default plan catalog; override by constructing Entitlements yourself
DEFAULT_PLANS = {
    "free": Plan(name="free", features=set(), limits={"projects": 1, "seats": 1}),
    "pro":  Plan(name="pro", features={"premium", "export"}, limits={"projects": 50, "seats": 10}),
    "team": Plan(name="team", features={"premium", "export", "sso"}, limits={"projects": -1, "seats": -1}),
}

def default_entitlements() -> Entitlements:
    return Entitlements(dict(DEFAULT_PLANS))

def feature_allowed(subscription, feature: str, plans: dict | None = None) -> bool:
    """Resolve the effective plan from the subscription's live status, then gate."""
    from scrapyard.billing.subscription_status import access_plan
    ent = Entitlements(plans or dict(DEFAULT_PLANS))
    return ent.allows(access_plan(subscription), feature)


def _selftest() -> None:
    class _Sub:
        def __init__(self, plan, status):
            self.plan, self.status = plan, status

    ent = default_entitlements()
    assert ent.allows("pro", "premium") is True
    assert ent.allows("free", "premium") is False
    assert ent.allows("team", "sso") is True
    assert ent.allows("pro", "sso") is False

    # live-status gating: canceled pro falls back to free
    assert feature_allowed(_Sub("pro", "active"), "export") is True
    assert feature_allowed(_Sub("pro", "canceled"), "export") is False
    assert feature_allowed(None, "export") is False

    # custom plan catalog override
    custom = {"free": Plan(name="free", features={"export"}, limits={})}
    assert feature_allowed(_Sub("pro", "canceled"), "export", plans=custom) is True


if __name__ == "__main__":
    _selftest()
    print("entitlements selftest OK")
