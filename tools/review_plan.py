#!/usr/bin/env python3
"""
review_plan.py — run the full reasoning pipeline over a plan.

Writes CONFIDENCE/OPERATIONS/FITNESS/SIMULATION/DECISIONS/RISK_REGISTER for an
assembled app, or (without --out) prints a console summary.

    python tools/review_plan.py <pattern> --domain d [--stage s] [--users N] [--include a,b] [--exclude a,b] [--out dir]
"""
from __future__ import annotations
import json, os, sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
RISKS = os.path.join(ROOT, "risks", "risk_rules.json")


def gen_decisions(pattern, domain_name, stage, present, out):
    import alternatives as A
    st = stage or "growth"
    L = [f"# Architecture decisions\n", f"- Pattern: **{pattern}**",
         f"- Domain: **{domain_name or 'none'}**", f"- Stage: **{st}**",
         f"- Date: {date.today().isoformat()}\n", "## Strategy choices\n"]
    for cap in A.all_caps():
        spec = A.load(cap)
        hints = {o.get("part_hint") for o in spec["options"]}
        if cap in present or (hints & present):
            ranked = sorted(spec["options"], key=lambda o: A.score(o, st), reverse=True)
            best = ranked[0]
            L.append(f"### {cap}: chose **{best['label']}** (score {A.score(best, st)} @ {st})")
            L.append(f"- Why: {best['notes']}")
            alt = ", ".join(f"{o['label']} ({A.score(o, st)})" for o in ranked[1:])
            if alt: L.append(f"- Alternatives: {alt}")
            L.append("")
    open(os.path.join(out, "DECISIONS.md"), "w", encoding="utf-8").write("\n".join(L))


def gen_risk_register(present, domain, out):
    rr = json.load(open(RISKS, encoding="utf-8"))
    L = ["# Risk register\n", "Risks implied by the selected capabilities and domain.\n"]
    for cap, risks in rr["by_capability"].items():
        if cap in present:
            L.append(f"## {cap}")
            L.extend(f"- {r}" for r in risks); L.append("")
    if domain:
        sens = domain.get("data_sensitivity", "low")
        for r in rr["by_domain_sensitivity"].get(sens, []):
            L.append(f"- (domain {sens}) {r}")
    open(os.path.join(out, "RISK_REGISTER.md"), "w", encoding="utf-8").write("\n".join(L))


def write_docs(plan, out, users):
    """Write all reasoning docs from a plan dict (from resolve.plan_from_args)."""
    import confidence_report as CR, ops_review as OR, fitness_review as FR, simulate_plan as SP
    os.makedirs(out, exist_ok=True)
    part_caps, present = plan["part_caps"], plan["present"]
    pn, dn, stage = plan["pattern_name"], plan["domain_name"], plan["stage"]
    open(os.path.join(out, "CONFIDENCE.md"), "w", encoding="utf-8").write(CR.render_md(CR.summarize(part_caps)))
    open(os.path.join(out, "OPERATIONS.md"), "w", encoding="utf-8").write(OR.render_md(OR.review(present)))
    fr = FR.evaluate(pn, dn, stage, users, include=plan["include"], exclude=plan["exclude"])
    open(os.path.join(out, "FITNESS.md"), "w", encoding="utf-8").write(FR.render_md(pn, dn, fr))
    open(os.path.join(out, "SIMULATION.md"), "w", encoding="utf-8").write(SP.render_md(SP.analyze(present)))
    gen_decisions(pn, dn, stage, present, out)
    gen_risk_register(present, plan["domain"], out)
    return fr


def main(argv):
    if not argv:
        print(__doc__); return 2
    import resolve as R, validate_assembly as VA, fitness_review as FR
    plan = R.plan_from_args(argv)
    if not plan:
        print(f"unknown pattern: {argv[0]}"); return 1
    users = int(argv[argv.index("--users") + 1]) if "--users" in argv else None
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    findings = VA.run_rules(plan["part_caps"], stage=plan["stage"], res=plan["res"],
                            graph_stage_of=(R.load_stages()["stage_of"] if plan["stage"] else None))
    worst = "PASS"
    for _, s, _ in findings:
        if s == "FAIL": worst = "FAIL"
        elif s == "WARN" and worst != "FAIL": worst = "WARN"
    if out:
        fr = write_docs(plan, out, users)
        print(f"reviewed {plan['pattern_name']} -> {out}")
        print(f"  validation: {worst}   fitness: {fr['verdict']}")
        print("  wrote CONFIDENCE/OPERATIONS/FITNESS/SIMULATION/DECISIONS/RISK_REGISTER")
    else:
        fr = FR.evaluate(plan["pattern_name"], plan["domain_name"], plan["stage"], users,
                         include=plan["include"], exclude=plan["exclude"])
        print(f"REVIEW {plan['pattern_name']}"
              + (f"+{plan['domain_name']}" if plan["domain_name"] else "")
              + (f" @{plan['stage']}" if plan["stage"] else ""))
        print(f"  parts: {len(plan['part_caps'])}   validation: {worst}   fitness: {fr['verdict']}")
        for sev, msg in fr["findings"]:
            print(f"    [{sev}] {msg}")
        print("  (pass --out <dir> to write the full document dossier)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
