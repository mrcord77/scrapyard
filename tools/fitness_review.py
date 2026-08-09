#!/usr/bin/env python3
"""
fitness_review.py — is this architecture appropriate, not just correct?

Validation asks "does it hold together?"; fitness asks "is it the right amount
of architecture for this product?" Something can pass validation and still be
overbuilt (multitenancy for a 5-user tool) or underbuilt (a high-sensitivity
domain with no encryption/audit).

    python tools/fitness_review.py <pattern> --domain <d> [--stage s] \
        [--users N] [--md <dir>]

Verdict: FIT | OVERBUILT | UNDERBUILT | RISKY | NEEDS_DECISION
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

STAGE_ORDER = ["mvp", "growth", "scale", "enterprise"]
# subsystems that are heavy/premature for a small early build
HEAVY = {"multitenancy_core": "enterprise", "compliance_gdpr": "enterprise",
         "metering_billing": "scale", "rag_stack": "scale", "agent_stack": "scale"}


def evaluate(pattern_name, domain_name, stage, users, include=None, exclude=None):
    import resolve as R
    argv = [pattern_name]
    if domain_name: argv += ["--domain", domain_name]
    if stage: argv += ["--stage", stage]
    if include: argv += ["--include", ",".join(include)]
    if exclude: argv += ["--exclude", ",".join(exclude)]
    plan = R.plan_from_args(argv)
    if not plan:
        return None
    domain = plan["domain"]
    subs = set(plan["res"]["subsystems"])
    caps = plan["part_caps"]

    findings = []  # (severity, msg)  severity in OVER/UNDER/RISK/DECISION
    eff_stage = stage or "enterprise"
    si = STAGE_ORDER.index(eff_stage)

    # OVERBUILT: heavy subsystems present below their recommended stage, or tiny user base
    for sub, min_stage in HEAVY.items():
        if sub in subs and (si < STAGE_ORDER.index(min_stage) or (users and users < 1000)):
            findings.append(("OVER", f"{sub} is heavy for "
                             + (f"{users} users" if users else f"stage {eff_stage}")
                             + f" (usually {min_stage})"))

    # Domain sensitivity checks (UNDER / RISK)
    if domain:
        sens = domain.get("data_sensitivity", "low")
        if sens == "high":
            if "field_encryption" not in caps:
                findings.append(("UNDER", "high-sensitivity domain without field_encryption"))
            if not ({"audit_logs", "structured_logging"} & caps):
                findings.append(("UNDER", "high-sensitivity domain without audit/structured logging"))
            if "gdpr_dsr" not in caps and "account_deletion" not in caps:
                findings.append(("RISK", "high-sensitivity domain without deletion/DSR path"))
            min_st = domain.get("minimum_security_stage", "mvp")
            if STAGE_ORDER.index(eff_stage) < STAGE_ORDER.index(min_st):
                findings.append(("RISK", f"stage {eff_stage} below domain minimum {min_st}"))
        if domain.get("regulated_data") and "compliance_gdpr" not in subs:
            findings.append(("DECISION", "regulated domain without a compliance subsystem — confirm obligations"))

    # verdict precedence: RISK > UNDER > OVER > DECISION > FIT
    sev = {f[0] for f in findings}
    if "RISK" in sev:
        verdict = "RISKY"
    elif "UNDER" in sev:
        verdict = "UNDERBUILT"
    elif "OVER" in sev:
        verdict = "OVERBUILT"
    elif "DECISION" in sev:
        verdict = "NEEDS_DECISION"
    else:
        verdict = "FIT"
    return {"verdict": verdict, "findings": findings, "stage": eff_stage,
            "users": users, "subsystems": len(subs), "parts": len(caps)}


def render_md(pattern, domain, r) -> str:
    L = [f"# Fitness review — {r['verdict']}\n",
         f"Pattern **{pattern}**" + (f", domain **{domain}**" if domain else "")
         + f", stage **{r['stage']}**"
         + (f", ~{r['users']} users" if r['users'] else "") + ".\n"]
    if r["findings"]:
        L.append("## Findings")
        for sev, msg in r["findings"]:
            L.append(f"- **{sev}** — {msg}")
    else:
        L.append("No fitness concerns: complexity matches stage and domain risk.")
    return "\n".join(L)


def main(argv):
    if not argv:
        print(__doc__); return 2
    pattern = argv[0]
    domain = argv[argv.index("--domain") + 1] if "--domain" in argv else None
    stage = argv[argv.index("--stage") + 1] if "--stage" in argv else None
    users = int(argv[argv.index("--users") + 1]) if "--users" in argv else None
    inc = argv[argv.index("--include") + 1].split(",") if "--include" in argv else None
    exc = argv[argv.index("--exclude") + 1].split(",") if "--exclude" in argv else None
    r = evaluate(pattern, domain, stage, users, include=inc, exclude=exc)
    if not r:
        print(f"unknown pattern: {pattern}"); return 1
    if "--md" in argv:
        out = argv[argv.index("--md") + 1]
        open(os.path.join(out, "FITNESS.md"), "w", encoding="utf-8").write(render_md(pattern, domain, r))
        print(f"wrote FITNESS.md — {r['verdict']}")
    else:
        print(f"VERDICT: {r['verdict']}  (stage={r['stage']}, "
              f"subsystems={r['subsystems']}, parts={r['parts']})")
        for sev, msg in r["findings"]:
            print(f"  [{sev:8}] {msg}")
        if not r["findings"]:
            print("  no concerns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
