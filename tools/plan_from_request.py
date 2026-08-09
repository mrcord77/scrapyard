#!/usr/bin/env python3
"""
plan_from_request.py — turn a product request into a build spec.

Maps a structured build request (product_type + domain + stage + constraints)
to a concrete pattern/domain/stage the resolver understands. The product_type ->
pattern mapping is a transparent keyword heuristic, not a learned model — it
prints what it matched so the choice is auditable.

    python tools/plan_from_request.py specs/examples/sobriety_journal.json [--out spec.json]
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# keyword -> pattern, checked in order; first match wins
PATTERN_MAP = [
    (("marketplace",), "marketplace"),
    (("crm", "customer relationship"), "crm"),
    (("ticket", "support desk", "helpdesk"), "ticketing_system"),
    (("knowledge base", "help center"), "knowledge_base"),
    (("documentation", "docs site"), "documentation_site"),
    (("course", "learning", "lms"), "course_platform"),
    (("directory", "listing site"), "directory_site"),
    (("job board", "jobs"), "job_board"),
    (("agent", "rag", "llm", "ai platform"), "agent_platform"),
    (("api product", "api-first", "developer api"), "api_product"),
    (("mobile",), "mobile_app"),
    (("desktop",), "desktop_tool"),
    (("subscription", "saas"), "saas_subscription_app"),
    (("content", "blog", "marketing site"), "content_site"),
]


def map_pattern(product_type: str) -> tuple[str, str]:
    pt = product_type.lower()
    for keys, pat in PATTERN_MAP:
        for k in keys:
            if k in pt:
                return pat, f"matched '{k}'"
    return "web_application", "no keyword matched — defaulted to web_application"


def main(argv):
    if not argv:
        print(__doc__); return 2
    req = json.load(open(argv[0], encoding="utf-8"))
    pattern, why = map_pattern(req.get("product_type", ""))
    domain = req.get("domain")
    stage = req.get("stage", "mvp")

    # validate domain exists
    if domain and not os.path.isdir(os.path.join(ROOT, "domains", domain)):
        print(f"warning: domain '{domain}' not found; proceeding without it")
        domain = None

    spec = {
        "schema": "scrapyard/build_spec@1",
        "pattern": pattern, "domain": domain, "stage": stage,
        "expected_users": req.get("expected_users"),
        "must_have": req.get("must_have", []),
        "must_not": req.get("must_not", []),
        "data_sensitivity": req.get("data_sensitivity"),
        "mapping_reason": why, "from_request": req.get("product_type", ""),
    }
    print(f"product_type: {req.get('product_type','')!r}")
    print(f"  -> pattern: {pattern}  ({why})")
    print(f"  -> domain:  {domain}")
    print(f"  -> stage:   {stage}")
    if spec["must_have"]:
        print(f"  + must_have: {', '.join(spec['must_have'])}")
    if spec["must_not"]:
        print(f"  - must_not:  {', '.join(spec['must_not'])}")
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
        json.dump(spec, open(out, "w", encoding="utf-8"), indent=2)
        print(f"wrote build spec -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
