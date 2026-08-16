"""
subscription_status — Resolve a customer's current plan/status.

### PART-META-JSON
{
  "name": "subscription_status",
  "layer": "billing",
  "purpose": "Resolve a customer's current plan/status.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: is_active(subscription); access_plan(subscription).",
  "outputs": "Returns: is_active -> bool; access_plan -> str.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `is_active` from `scrapyard.billing.subscription_status` and call it as shown in `example`; run `py -m scrapyard.billing.subscription_status` to see its offline selftest.",
  "example": "from scrapyard.billing.subscription_status import is_active",
  "import_path": "scrapyard.billing.subscription_status"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

# which lifecycle states grant product access
ACTIVE_STATES = {"active", "trialing"}

def is_active(subscription) -> bool:
    """True if the subscription currently entitles the user to paid features."""
    return bool(subscription) and getattr(subscription, "status", None) in ACTIVE_STATES

def access_plan(subscription) -> str:
    """The plan name to gate on: the subscription's plan if active, else 'free'."""
    return subscription.plan if is_active(subscription) else "free"


def _selftest() -> None:
    class _Sub:
        def __init__(self, plan, status):
            self.plan, self.status = plan, status

    assert is_active(_Sub("pro", "active")) is True
    assert is_active(_Sub("pro", "trialing")) is True
    for dead in ("canceled", "past_due", "incomplete", None):
        assert is_active(_Sub("pro", dead)) is False
    assert is_active(None) is False

    assert access_plan(_Sub("pro", "active")) == "pro"
    assert access_plan(_Sub("team", "trialing")) == "team"
    assert access_plan(_Sub("pro", "canceled")) == "free"
    assert access_plan(None) == "free"


if __name__ == "__main__":
    _selftest()
    print("subscription_status selftest OK")
