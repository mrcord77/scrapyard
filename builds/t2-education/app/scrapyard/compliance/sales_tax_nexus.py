"""
sales_tax_nexus — US economic-nexus (post-Wayfair) sales-tax exposure map.

### PART-META-JSON
{
  "name": "sales_tax_nexus",
  "layer": "compliance",
  "purpose": "Map where a SaaS/digital seller has crossed a state's economic-nexus sales-tax threshold (revenue OR transaction count) and must register, before a state finds them first.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Per-state sales aggregates (gross revenue + transaction count for a 12-month period), and an optional override of the built-in dated threshold table.",
  "outputs": "Per-state findings (triggered | approaching | monitor | none | no_sales_tax) with the prong crossed, headroom to the threshold, SaaS-taxability posture, and a registration recommendation; plus a portfolio summary.",
  "files_created": [],
  "security_notes": "NOT LEGAL OR TAX ADVICE. The bundled thresholds are a DATED screening baseline (see THRESHOLDS_AS_OF) and change frequently by statute — verify each state before registering or remitting. This part computes exposure; it does not file. Validate all external input; never log secrets/PII.",
  "ai_usage": "Aggregate the customer ledger to per-state StateSales (see sales_by_state_from_ledger), call evaluate(), then summarize() to get the register-now list. Refresh THRESHOLDS with a verified table for production.",
  "example": "from scrapyard.compliance.sales_tax_nexus import StateSales, evaluate, summarize; f = evaluate([StateSales('CA', 620000, 900), StateSales('TX', 130000, 400)]); print(summarize(f))",
  "import_path": "scrapyard.compliance.sales_tax_nexus"
}
### END-PART-META
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

STATUS = "core"

# ---------------------------------------------------------------------------
# DISCLAIMER — read before trusting a number.
# ---------------------------------------------------------------------------
DISCLAIMER = (
    "This is an automated SCREENING tool, not legal or tax advice. Economic-nexus "
    "thresholds, the measurement basis (gross vs. retail vs. taxable receipts), the "
    "look-back period, and whether SaaS/digital goods are taxable all vary by state "
    "and change often. Confirm every 'triggered' state against its current statute "
    "or with a sales-tax professional before registering or remitting."
)

# Effective date of the bundled table. Bump this whenever THRESHOLDS is refreshed.
THRESHOLDS_AS_OF = "2025-01"

# States with NO statewide general sales tax. (Alaska has no *statewide* tax but
# does have local sales taxes via the ARSSTC — treated as a special screen.)
NO_SALES_TAX_STATES = {"DE", "MT", "NH", "OR"}
ALASKA_LOCAL_ONLY = "AK"  # no statewide tax; local economic nexus ~$100k (ARSSTC)

# Economic-nexus thresholds for remote sellers: state -> (revenue_usd, txn_count).
# txn_count is None where the state has no transaction prong (or repealed it).
# Measured over the current or prior calendar year unless a state differs.
# DATED BASELINE (see THRESHOLDS_AS_OF) — verify before production use.
THRESHOLDS: Dict[str, Tuple[int, Optional[int]]] = {
    "AL": (250_000, None), "AZ": (100_000, None), "AR": (100_000, 200),
    "CA": (500_000, None), "CO": (100_000, None), "CT": (100_000, 200),
    "DC": (100_000, 200), "FL": (100_000, None), "GA": (100_000, 200),
    "HI": (100_000, 200), "ID": (100_000, None), "IL": (100_000, 200),
    "IN": (100_000, None), "IA": (100_000, None), "KS": (100_000, None),
    "KY": (100_000, 200), "LA": (100_000, None), "ME": (100_000, None),
    "MD": (100_000, 200), "MA": (100_000, None), "MI": (100_000, 200),
    "MN": (100_000, 200), "MS": (250_000, None), "MO": (100_000, None),
    "NE": (100_000, 200), "NV": (100_000, 200), "NJ": (100_000, 200),
    "NM": (100_000, None), "NY": (500_000, 100), "NC": (100_000, None),
    "ND": (100_000, None), "OH": (100_000, 200), "OK": (100_000, None),
    "PA": (100_000, None), "RI": (100_000, 200), "SC": (100_000, None),
    "SD": (100_000, None), "TN": (100_000, None), "TX": (500_000, None),
    "UT": (100_000, 200), "VT": (100_000, 200), "VA": (100_000, 200),
    "WA": (100_000, None), "WV": (100_000, 200), "WI": (100_000, None),
    "WY": (100_000, None),
}
# CT requires BOTH revenue AND transactions (an "and" state). Most are "or".
AND_STATES = {"CT", "NY"}

# SaaS taxability posture. Only high-confidence entries are asserted; everything
# else defaults to "review" — the honest answer for a screening tool. taxability
# does not affect NEXUS (you can owe registration on exempt sales), but it drives
# whether you must actually COLLECT once registered.
SAAS_TAXABLE = {"AZ", "CT", "HI", "MA", "NM", "NY", "OH", "PA", "RI", "SD",
                "TN", "TX", "UT", "WA", "WV", "DC"}
SAAS_EXEMPT = {"CA", "FL", "GA", "IL", "VA", "NV", "MO", "AR", "WI", "MD"}


def saas_taxability(state: str) -> str:
    s = state.upper()
    if s in SAAS_TAXABLE:
        return "taxable"
    if s in SAAS_EXEMPT:
        return "exempt"
    return "review"


@dataclass
class StateSales:
    """A seller's 12-month sales into one state."""
    state: str
    gross_revenue: float
    transactions: int = 0


@dataclass
class NexusFinding:
    state: str
    status: str                 # triggered | approaching | monitor | none | no_sales_tax
    revenue: float
    transactions: int
    revenue_threshold: Optional[int]
    txn_threshold: Optional[int]
    prong: str                  # which prong crossed / closest ("revenue"|"transactions"|"both"|"")
    headroom_pct: float         # how far into the threshold (>=1.0 means crossed)
    saas_taxability: str
    recommendation: str


def _closest_pct(rev: float, txns: int, rev_t: Optional[int],
                 txn_t: Optional[int]) -> Tuple[float, str]:
    """Return (fraction-of-threshold-reached, which-prong-is-closest)."""
    rev_frac = (rev / rev_t) if rev_t else 0.0
    txn_frac = (txns / txn_t) if txn_t else 0.0
    if txn_frac > rev_frac:
        return txn_frac, "transactions"
    return rev_frac, "revenue"


def evaluate(sales: List[StateSales], *, approaching: float = 0.8,
             monitor: float = 0.5,
             thresholds: Optional[Dict[str, Tuple[int, Optional[int]]]] = None
             ) -> List[NexusFinding]:
    """Classify each state's exposure. `approaching`/`monitor` are the fractions
    of a threshold at which a state is flagged before it is crossed."""
    table = thresholds or THRESHOLDS
    out: List[NexusFinding] = []
    for s in sales:
        st = s.state.upper()
        if st in NO_SALES_TAX_STATES:
            out.append(NexusFinding(st, "no_sales_tax", s.gross_revenue,
                                    s.transactions, None, None, "", 0.0, "n/a",
                                    "No statewide sales tax — nothing to register."))
            continue
        rev_t, txn_t = table.get(st, (None, None))
        if rev_t is None and txn_t is None:
            # Unknown state (e.g. AK local-only, or a typo) — flag for manual review.
            out.append(NexusFinding(st, "monitor", s.gross_revenue, s.transactions,
                                    None, None, "", 0.0, saas_taxability(st),
                                    "No bundled threshold — verify this jurisdiction manually."))
            continue
        rev_hit = bool(rev_t) and s.gross_revenue >= rev_t
        txn_hit = bool(txn_t) and s.transactions >= txn_t
        crossed = (rev_hit and txn_hit) if st in AND_STATES else (rev_hit or txn_hit)
        frac, closest = _closest_pct(s.gross_revenue, s.transactions, rev_t, txn_t)
        if crossed:
            prong = "both" if (rev_hit and txn_hit) else ("revenue" if rev_hit else "transactions")
            tax = saas_taxability(st)
            rec = (f"REGISTER: nexus crossed on {prong}. "
                   + ("Collect tax on taxable sales."
                      if tax == "taxable" else
                      "Confirm SaaS taxability — you may owe registration even if sales are exempt."))
            status = "triggered"
        elif frac >= approaching:
            status, prong = "approaching", closest
            rec = f"Approaching the {closest} threshold ({frac:.0%}). Turn on tax collection now to avoid back-tax."
        elif frac >= monitor:
            status, prong = "monitor", closest
            rec = f"At {frac:.0%} of the {closest} threshold. Track monthly."
        else:
            status, prong = "none", ""
            rec = "Below screening thresholds."
        out.append(NexusFinding(st, status, s.gross_revenue, s.transactions,
                                rev_t, txn_t, prong, round(frac, 3),
                                saas_taxability(st), rec))
    return out


def summarize(findings: List[NexusFinding]) -> Dict[str, object]:
    """Portfolio view: the register-now list, the watch list, and the caveat."""
    triggered = [f.state for f in findings if f.status == "triggered"]
    approaching = [f.state for f in findings if f.status == "approaching"]
    review_tax = [f.state for f in findings
                  if f.status == "triggered" and f.saas_taxability == "review"]
    return {
        "thresholds_as_of": THRESHOLDS_AS_OF,
        "states_evaluated": len(findings),
        "register_now": sorted(triggered),
        "approaching": sorted(approaching),
        "needs_taxability_determination": sorted(review_tax),
        "disclaimer": DISCLAIMER,
    }


def sales_by_state_from_ledger(rows: List[dict], *, state_key: str = "state",
                               amount_key: str = "amount") -> List[StateSales]:
    """Aggregate a flat charge/invoice ledger (one row per sale, each carrying a
    destination state + amount) into per-state StateSales. Amounts are summed and
    transactions counted. Rows missing a state are skipped (surface those upstream)."""
    agg: Dict[str, StateSales] = {}
    for r in rows:
        st = (r.get(state_key) or "").strip().upper()
        if not st:
            continue
        cur = agg.get(st) or StateSales(st, 0.0, 0)
        cur.gross_revenue += float(r.get(amount_key) or 0)
        cur.transactions += 1
        agg[st] = cur
    return list(agg.values())


def _selftest() -> None:
    # CA: revenue-only $500k state. 620k crosses; SaaS exempt in CA.
    # TX: $500k state. 130k is below -> none (26% of 500k).
    # NY: AND state ($500k AND 100 txns). 510k + 40 txns -> NOT crossed (txns short).
    # WA: $100k, SaaS taxable. 150k crosses.
    # OR: no sales tax.
    sales = [StateSales("CA", 620_000, 900), StateSales("TX", 130_000, 400),
             StateSales("NY", 510_000, 40), StateSales("WA", 150_000, 120),
             StateSales("OR", 999_999, 5000), StateSales("GA", 90_000, 210)]
    f = {x.state: x for x in evaluate(sales)}
    assert f["CA"].status == "triggered" and f["CA"].prong == "revenue"
    assert f["CA"].saas_taxability == "exempt"
    assert f["TX"].status == "none", f["TX"].status
    assert f["NY"].status != "triggered", "NY needs BOTH prongs"
    assert f["WA"].status == "triggered" and f["WA"].saas_taxability == "taxable"
    assert f["OR"].status == "no_sales_tax"
    # GA: $100k OR 200 txns — 90k revenue but 210 txns crosses the txn prong.
    assert f["GA"].status == "triggered" and f["GA"].prong == "transactions"

    s = summarize(evaluate(sales))
    assert "CA" in s["register_now"] and "WA" in s["register_now"]
    assert "OR" not in s["register_now"] and "TX" not in s["register_now"]
    assert s["thresholds_as_of"] == THRESHOLDS_AS_OF

    # ledger aggregation
    ledger = [{"state": "wa", "amount": 50}, {"state": "WA", "amount": 70},
              {"state": "CA", "amount": 10}, {"state": "", "amount": 5}]
    agg = {x.state: x for x in sales_by_state_from_ledger(ledger)}
    assert agg["WA"].gross_revenue == 120 and agg["WA"].transactions == 2
    assert "CA" in agg and len(agg) == 2  # blank-state row skipped

    # approaching band: 85% of a $100k state with no txn prong
    ap = evaluate([StateSales("PA", 85_000, 0)])[0]
    assert ap.status == "approaching", ap.status


if __name__ == "__main__":
    _selftest()
    print("sales_tax_nexus selftest OK")
