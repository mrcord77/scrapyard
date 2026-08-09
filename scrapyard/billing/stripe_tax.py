"""
stripe_tax — Turn on Stripe Tax so sales tax is collected at checkout.

### PART-META-JSON
{
  "name": "stripe_tax",
  "layer": "billing",
  "purpose": "Enable Stripe Tax on Checkout Sessions and Subscriptions so the correct sales tax is calculated and collected at checkout, plus register tax collection per nexus state — the collection half of sales-tax compliance.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "stripe"
  ],
  "inputs": "Nexus states (from sales_tax_nexus), the product kind (saas/digital/downloadable), and Checkout/Subscription creation params to augment.",
  "outputs": "Augmented Stripe API params with automatic_tax enabled and a product tax code set; an ordered enablement checklist; and a helper that registers tax collection for a state via the Stripe Tax Registrations API.",
  "files_created": [],
  "security_notes": "NOT TAX ADVICE. Enabling automatic_tax makes Stripe calculate tax but you must still (a) register with each state where you have nexus and (b) file/remit — Stripe Tax calculates and (optionally) files, it does not absolve the obligation. Requires a live STRIPE_API_KEY and a configured origin address in the Stripe dashboard. Never log the API key or customer PII.",
  "ai_usage": "Use enablement_checklist() to drive setup; merge checkout_session_params()/subscription_params() into your stripe.checkout.Session.create/Subscription.create calls; call register_state() for each state sales_tax_nexus flags as triggered.",
  "example": "from scrapyard.billing.stripe_tax import checkout_session_params, TAX_CODES; params = {**base, **checkout_session_params(collect_address=True)}",
  "import_path": "scrapyard.billing.stripe_tax"
}
### END-PART-META
"""
from __future__ import annotations

from typing import Dict, List, Optional

STATUS = "core"

# Stripe product tax codes (txcd_*) for common digital products. These select the
# taxability treatment Stripe applies per jurisdiction; pick the one that matches
# what you sell. Verify against Stripe's current tax-code list before production.
TAX_CODES = {
    "saas": "txcd_10103001",          # Software as a service (SaaS) - business use
    "saas_personal": "txcd_10103000",  # SaaS - personal use
    "digital_goods": "txcd_10501000",  # Digital goods / downloadable software
    "ebook": "txcd_10302000",          # Electronic books
    "digital_service": "txcd_10000000",  # General - electronically supplied services
}


def enablement_checklist() -> List[Dict[str, str]]:
    """The ordered, do-this-once setup for Stripe Tax. Each step names the action
    and where it happens (dashboard vs. code)."""
    return [
        {"step": "1", "where": "dashboard",
         "action": "Enable Stripe Tax (Settings -> Tax) and set your origin address / business location."},
        {"step": "2", "where": "code/dashboard",
         "action": "Assign a product tax code to each product/price (see TAX_CODES) so SaaS vs. digital goods is taxed correctly."},
        {"step": "3", "where": "code",
         "action": "Add automatic_tax={'enabled': True} to every Checkout Session and Subscription (see checkout_session_params/subscription_params)."},
        {"step": "4", "where": "code",
         "action": "Collect the customer's address at checkout (billing_address_collection='required') so Stripe can determine the jurisdiction."},
        {"step": "5", "where": "dashboard/api",
         "action": "For each state where sales_tax_nexus reports 'triggered', add a Tax Registration (Settings -> Tax -> Registrations, or register_state())."},
        {"step": "6", "where": "process",
         "action": "Decide filing: Stripe Tax can calculate + optionally file, but registration and remittance stay your obligation. Build the filing calendar (sales_tax_filing_calendar)."},
        {"step": "7", "where": "code",
         "action": "Test in a Stripe test-mode checkout from a taxable-state address; confirm tax appears as a line item before going live."},
    ]


def checkout_session_params(*, collect_address: bool = True) -> Dict[str, object]:
    """Params to merge into stripe.checkout.Session.create(...) to collect tax.
    automatic_tax lets Stripe compute tax; address collection gives it the
    jurisdiction it needs to do so."""
    params: Dict[str, object] = {"automatic_tax": {"enabled": True}}
    if collect_address:
        params["billing_address_collection"] = "required"
        # For shipped/digital destination-based tax, also let Stripe use the
        # address the customer enters as the tax location.
        params["customer_update"] = {"address": "auto"}
    return params


def subscription_params() -> Dict[str, object]:
    """Params to merge into stripe.Subscription.create(...) so recurring invoices
    carry tax. The customer must already have a tax-eligible address on file."""
    return {"automatic_tax": {"enabled": True}}


def price_tax_code(kind: str) -> str:
    """Resolve a product kind to a Stripe tax code; defaults to general SaaS."""
    return TAX_CODES.get(kind, TAX_CODES["saas"])


def register_state(state: str, *, country: str = "US",
                   active_from: str = "now") -> Dict[str, object]:
    """Register tax collection for a US state via the Stripe Tax Registrations API.
    Requires STRIPE_API_KEY. Returns the created registration (or a deterministic
    local stub when no key is set, so wiring is testable offline).

    NOTE: creating a Stripe registration records that YOU registered — you must
    first actually register with the state's revenue department to get authority
    to collect. Stripe's registration object mirrors that; it does not create it."""
    import os
    st = state.strip().upper()
    if len(st) != 2:
        raise ValueError(f"expected a 2-letter state code, got {state!r}")
    key = os.environ.get("STRIPE_API_KEY")
    if not key:
        return {"id": f"taxreg_local_{country}_{st}", "state": st,
                "country": country, "active_from": active_from, "live": False}
    import stripe
    stripe.api_key = key
    reg = stripe.tax.Registration.create(
        country=country, active_from=active_from,
        country_options={country: {"type": "state_sales_tax",
                                   "state_sales_tax": {"state": st}}}
        if country == "US" else {country: {"type": "standard"}},
    )
    return {"id": reg["id"], "state": st, "country": country,
            "active_from": active_from, "live": True}


def registration_plan(triggered_states: List[str]) -> List[Dict[str, str]]:
    """Turn the nexus 'register_now' list into an ordered registration to-do."""
    return [{"state": s.upper(),
             "action": f"Register for a sales-tax permit in {s.upper()}, "
                       f"then add the Stripe Tax registration (register_state('{s.upper()}'))."}
            for s in sorted({t.upper() for t in triggered_states})]


def _selftest() -> None:
    cs = checkout_session_params()
    assert cs["automatic_tax"] == {"enabled": True}
    assert cs["billing_address_collection"] == "required"
    assert subscription_params()["automatic_tax"]["enabled"] is True

    assert price_tax_code("saas").startswith("txcd_")
    assert price_tax_code("unknown_kind") == TAX_CODES["saas"]  # safe default

    steps = enablement_checklist()
    assert steps[0]["step"] == "1" and len(steps) == 7
    assert any("automatic_tax" in s["action"] for s in steps)
    assert any("Registration" in s["action"] or "register" in s["action"].lower()
               for s in steps)

    # offline registration stub (no STRIPE_API_KEY in tests)
    reg = register_state("wa")
    assert reg["state"] == "WA" and reg["live"] is False
    try:
        register_state("Washington")
        assert False, "should reject non-2-letter codes"
    except ValueError:
        pass

    plan = registration_plan(["ca", "WA", "ca"])
    assert [p["state"] for p in plan] == ["CA", "WA"]  # deduped + sorted


if __name__ == "__main__":
    _selftest()
    print("stripe_tax selftest OK")
