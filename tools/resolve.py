#!/usr/bin/env python3
"""
resolve.py — the auto-assembly engine.

You no longer pick parts. You name a *pattern* (what you're building) and
optionally a *domain* (what world it lives in). The resolver walks the
capability graph and returns the exact set of parts:

    Pattern  ->  Subsystems (meta)  ->  Parts (concrete)  ->  Code
    Domain   ->  capability hints + entities/workflows/terminology

    python tools/resolve.py <pattern> [--domain <d>] [--out <dir>] [--json]
    python tools/resolve.py --list

Examples:
    python tools/resolve.py saas_subscription_app
    python tools/resolve.py saas_subscription_app --domain sobriety --out ./my_app
    python tools/resolve.py agent_platform --json

With --out it materializes a runnable app skeleton (reusing assemble_parts) and,
when a domain is given, writes DOMAIN.md with the entities/workflows/permissions
the AI should scaffold on top of the parts.
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

CAPS = os.path.join(ROOT, "capabilities", "capabilities.json")
PAT = os.path.join(ROOT, "patterns")
DOM = os.path.join(ROOT, "domains")
COMP = os.path.join(ROOT, "compositions")
LIFE = os.path.join(ROOT, "lifecycle", "stages.json")


def load_stages() -> dict | None:
    return json.load(open(LIFE, encoding="utf-8")) if os.path.exists(LIFE) else None


def filter_by_stage(wanted: list[str], stage: str, stages: dict) -> tuple[list[str], list[str]]:
    """Keep capabilities ranked at or below `stage`. Unclassified default to mvp."""
    order = stages["order"]
    if stage not in order:
        raise SystemExit(f"unknown stage: {stage} (choose from {', '.join(order)})")
    cap_rank = stages["stage_of"]
    limit = order.index(stage)
    kept, deferred = [], []
    for c in wanted:
        rank = order.index(cap_rank.get(c, "mvp"))
        (kept if rank <= limit else deferred).append(c)
    return kept, deferred


def load_graph() -> dict:
    with open(CAPS, encoding="utf-8") as f:
        return json.load(f)


def _read_pattern(name: str) -> dict | None:
    p = os.path.join(PAT, name, "pattern.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def load_pattern(name: str) -> dict | None:
    """Resolve a pattern, following `extends` and unioning required capabilities
    parent-first. Child keeps its own description; requires are deduped in order."""
    spec = _read_pattern(name)
    if not spec:
        return None
    chain, seen, cur = [], set(), spec
    while cur:
        if cur["name"] in seen:
            break
        seen.add(cur["name"])
        chain.append(cur)
        parent = cur.get("extends")
        cur = _read_pattern(parent) if parent else None
    requires: list[str] = []
    for node in reversed(chain):          # base -> leaf
        for cap in node.get("requires", []):
            if cap not in requires:
                requires.append(cap)
    return {"name": spec["name"], "description": spec.get("description", ""),
            "extends_chain": [n["name"] for n in chain], "requires": requires}


def _read_domain(name: str) -> dict | None:
    p = os.path.join(DOM, name, "domain.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def load_domain(name: str) -> dict | None:
    """Resolve a domain, following `extends`. Entities merge by name (child wins);
    terminology merges (child wins); lists concat+dedup; hints union."""
    spec = _read_domain(name)
    if not spec:
        return None
    chain, seen, cur = [], set(), spec
    while cur:
        if cur["name"] in seen:
            break
        seen.add(cur["name"])
        chain.append(cur)
        parent = cur.get("extends")
        cur = _read_domain(parent) if parent else None
    merged = {"name": spec["name"], "label": spec.get("label", spec["name"]),
              "notes": spec.get("notes", ""), "terminology": {}, "entities": [],
              "workflows": [], "permissions": [], "reports": [], "capability_hints": [],
              "extends_chain": [n["name"] for n in chain]}
    ent_by_name: dict[str, dict] = {}
    for node in reversed(chain):          # base -> leaf, leaf overrides
        merged["terminology"].update(node.get("terminology", {}))
        for e in node.get("entities", []):
            ent_by_name[e["name"]] = e     # child entity of same name replaces parent
        for k in ("workflows", "permissions", "reports", "capability_hints"):
            for x in node.get(k, []):
                if x not in merged[k]:
                    merged[k].append(x)
    merged["entities"] = list(ent_by_name.values())
    # carry sensitivity/governance fields, leaf-first (child wins)
    PASSTHROUGH = ("data_sensitivity", "sensitive_entities", "regulated_data",
                   "retention_requirements", "deletion_requirements",
                   "consent_requirements", "audit_requirements",
                   "minimum_security_stage", "privacy_notes", "route_policies",
                   "sensitive_fields", "exempt_fields", "retention_days", "many_to_many",
                   "brand", "home", "artifacts")
    for node in chain:  # leaf -> base
        for k in PASSTHROUGH:
            if k in node and k not in merged:
                merged[k] = node[k]
    return merged


def applicable_compositions(present: set[str]) -> list[dict]:
    """Recipes whose every bound capability is in the resolved plan."""
    out = []
    if not os.path.isdir(COMP):
        return out
    for name in sorted(os.listdir(COMP)):
        cj = os.path.join(COMP, name, "composition.json")
        if not os.path.exists(cj):
            continue
        c = json.load(open(cj, encoding="utf-8"))
        if all(b in present for b in c.get("binds", [])):
            out.append(c)
    return out


def resolve_capabilities(graph: dict, wanted: list[str]) -> dict:
    """Transitive closure over the capability graph. Cycle-safe via `visited`."""
    concrete, meta = graph["concrete"], graph["meta"]
    visited: set[str] = set()
    parts: dict[str, dict] = {}        # import_path -> {capability, status, layer, addition}
    subsystems: list[str] = []         # meta capabilities expanded, in encounter order
    unknown: list[str] = []

    def walk(cap: str):
        if cap in visited:
            return
        visited.add(cap)
        if cap in concrete:
            c = concrete[cap]
            parts[c["part"]] = {"capability": cap, "status": c["status"],
                                "layer": c["layer"], "addition": c.get("addition", False)}
            for r in c.get("requires", []):
                walk(r)
        elif cap in meta:
            if cap not in subsystems:
                subsystems.append(cap)
            for r in meta[cap]["requires"]:
                walk(r)
        else:
            if cap not in unknown:
                unknown.append(cap)

    for cap in wanted:
        walk(cap)

    core = sum(1 for p in parts.values() if p["status"] == "core")
    return {
        "requested": wanted,
        "subsystems": subsystems,
        "parts": parts,
        "unknown": unknown,
        "totals": {"parts": len(parts), "core": core,
                   "skeleton": len(parts) - core, "subsystems": len(subsystems)},
    }


def list_all() -> None:
    print("Patterns:")
    for n in sorted(os.listdir(PAT)) if os.path.isdir(PAT) else []:
        pj = os.path.join(PAT, n, "pattern.json")
        if os.path.exists(pj):
            d = json.load(open(pj, encoding="utf-8"))
            print(f"  {n:24} {d.get('description','')}")
    print("\nDomains:")
    for n in sorted(os.listdir(DOM)) if os.path.isdir(DOM) else []:
        dj = os.path.join(DOM, n, "domain.json")
        if os.path.exists(dj):
            d = json.load(open(dj, encoding="utf-8"))
            print(f"  {n:24} {d.get('label','')}")


def write_domain_md(out: str, domain: dict) -> None:
    L = [f"# Domain: {domain.get('label', domain['name'])}\n"]
    if domain.get("notes"):
        L.append(f"> {domain['notes']}\n")
    if domain.get("terminology"):
        L.append("## Terminology")
        for k, v in domain["terminology"].items():
            L.append(f"- **{k}** — {v}")
        L.append("")
    if domain.get("entities"):
        L.append("## Entities to scaffold")
        for e in domain["entities"]:
            fields = ", ".join(f["name"] if isinstance(f, dict) else f for f in e.get("fields", []))
            line = f"- **{e['name']}**: {fields}"
            if e.get("notes"):
                line += f"  _({e['notes']})_"
            L.append(line)
        L.append("")
    for key, head in [("workflows", "Workflows"), ("permissions", "Permissions"), ("reports", "Reports")]:
        if domain.get(key):
            L.append(f"## {head}")
            L.extend(f"- {x}" for x in domain[key])
            L.append("")
    with open(os.path.join(out, "DOMAIN.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def print_plan(pattern_name: str, domain_name: str | None, res: dict,
               chains: dict | None = None) -> None:
    t = res["totals"]
    print(f"\nPLAN  pattern={pattern_name}" + (f"  domain={domain_name}" if domain_name else ""))
    if chains and chains.get("pattern") and len(chains["pattern"]) > 1:
        print("  pattern inherits: " + " <- ".join(chains["pattern"]))
    if chains and chains.get("domain") and len(chains["domain"]) > 1:
        print("  domain inherits:  " + " <- ".join(chains["domain"]))
    print(f"  subsystems: {t['subsystems']}   parts: {t['parts']} "
          f"({t['core']} core, {t['skeleton']} skeleton)")
    print("  subsystems expanded: " + ", ".join(res["subsystems"]))
    by_layer: dict[str, list] = {}
    for ip, info in res["parts"].items():
        by_layer.setdefault(info["layer"], []).append((ip, info))
    print("  parts by layer:")
    for layer in sorted(by_layer):
        names = []
        for ip, info in sorted(by_layer[layer]):
            tag = "" if info["status"] == "core" else "·"
            plus = "+" if info["addition"] else ""
            names.append(f"{ip.split('.')[-1]}{tag}{plus}")
        print(f"    {layer:14} {', '.join(names)}")
    if res["unknown"]:
        print("  UNRESOLVED capabilities: " + ", ".join(res["unknown"]))
    print("  legend: ·=skeleton (stub)  +=addition beyond source map")
    # confidence-aware: report how trustworthy the resolved parts are
    try:
        import confidence_report as CR
        s = CR.summarize([i["capability"] for i in res["parts"].values()])
        dist = ", ".join(f"{k} {v}" for k, v in sorted(s["distribution"].items()))
        print(f"  plan confidence: avg {s['avg']} ({dist})")
    except Exception:
        pass
    present = set(res["subsystems"]) | {i["capability"] for i in res["parts"].values()}
    comps = applicable_compositions(present)
    if comps:
        print(f"  integration recipes that apply ({len(comps)}):")
        for c in comps:
            print(f"    {c['name']}: {' + '.join(c['binds'])}")


def write_compositions_md(out: str, comps: list[dict]) -> None:
    L = ["# Integration recipes for this app\n",
         "These capabilities are present together and need glue. Wire them as below.\n"]
    for c in comps:
        L.append(f"## {c['name']} — {' + '.join(c['binds'])}")
        L.append(f"_{c.get('problem','')}_\n")
        if c.get("glue"):
            L.append(f"**Glue:** {c['glue']}\n")
        if c.get("steps"):
            L.append("**Steps:**")
            L.extend(f"{i+1}. {s}" for i, s in enumerate(c["steps"]))
            L.append("")
        if c.get("owns_data"):
            L.append(f"**Shared data:** `{c['owns_data']}`\n")
    with open(os.path.join(out, "COMPOSITIONS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def plan_from_args(argv):
    """Shared plan builder: parse pattern/domain/stage/include/exclude from argv,
    resolve, and return everything tools need. One code path so enforcement is
    identical across resolve, review, ops, fitness, simulation, and cost."""
    graph = load_graph()
    pattern_name = argv[0]
    pattern = load_pattern(pattern_name)
    if not pattern:
        return None
    domain_name = argv[argv.index("--domain") + 1] if "--domain" in argv else None
    stage = argv[argv.index("--stage") + 1] if "--stage" in argv else None
    include = [c.strip() for c in argv[argv.index("--include") + 1].split(",")] if "--include" in argv else []
    exclude = [c.strip() for c in argv[argv.index("--exclude") + 1].split(",")] if "--exclude" in argv else []
    include = [c for c in include if c]
    exclude = [c for c in exclude if c]
    wanted = list(pattern["requires"])
    domain = load_domain(domain_name) if domain_name else None
    if domain:
        wanted += domain.get("capability_hints", [])
    if stage:
        wanted, _ = filter_by_stage(wanted, stage, load_stages())
    for c in include:
        if c not in wanted:
            wanted.append(c)
    if exclude:
        wanted = [c for c in wanted if c not in exclude]
    res = resolve_capabilities(graph, wanted)
    if exclude:
        res["parts"] = {ip: i for ip, i in res["parts"].items() if i["capability"] not in exclude}
        res["subsystems"] = [s for s in res["subsystems"] if s not in exclude]
    return {"pattern": pattern, "pattern_name": pattern_name, "domain": domain,
            "domain_name": domain_name, "stage": stage, "res": res,
            "include": include, "exclude": exclude,
            "part_caps": {i["capability"] for i in res["parts"].values()},
            "present": {i["capability"] for i in res["parts"].values()} | set(res["subsystems"])}


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "--list":
        list_all()
        return 0
    as_json = "--json" in argv
    out = None
    domain_name = None
    stage = None
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    if "--domain" in argv:
        domain_name = argv[argv.index("--domain") + 1]
    if "--stage" in argv:
        stage = argv[argv.index("--stage") + 1]
    include = argv[argv.index("--include") + 1].split(",") if "--include" in argv else []
    exclude = argv[argv.index("--exclude") + 1].split(",") if "--exclude" in argv else []
    include = [c.strip() for c in include if c.strip()]
    exclude = [c.strip() for c in exclude if c.strip()]
    pattern_name = argv[0]

    graph = load_graph()
    pattern = load_pattern(pattern_name)
    if not pattern:
        print(f"unknown pattern: {pattern_name} (try --list)")
        return 1
    wanted = list(pattern.get("requires", []))
    domain = None
    if domain_name:
        domain = load_domain(domain_name)
        if not domain:
            print(f"unknown domain: {domain_name} (try --list)")
            return 1
        wanted += domain.get("capability_hints", [])

    deferred: list[str] = []
    if stage:
        stages = load_stages()
        if not stages:
            print("no lifecycle/stages.json found")
            return 1
        wanted, deferred = filter_by_stage(wanted, stage, stages)

    # enforce explicit requirements: include forces caps in, exclude blocks them
    for c in include:
        if c not in wanted:
            wanted.append(c)
    if exclude:
        wanted = [c for c in wanted if c not in exclude]

    res = resolve_capabilities(graph, wanted)
    if exclude:
        # prune any parts pulled transitively whose capability is excluded
        res["parts"] = {ip: i for ip, i in res["parts"].items()
                        if i["capability"] not in exclude}
        res["subsystems"] = [s for s in res["subsystems"] if s not in exclude]

    if as_json:
        print(json.dumps({"pattern": pattern_name, "domain": domain_name,
                          "stage": stage, "deferred": deferred, **res}, indent=2))
    else:
        chains = {"pattern": pattern.get("extends_chain"),
                  "domain": domain.get("extends_chain") if domain else None}
        print_plan(pattern_name, domain_name, res, chains)
        if stage:
            print(f"  stage: {stage}  (deferred to later stages: "
                  + (", ".join(deferred) or "none") + ")")
        # feedback loop: surface lessons relevant to this plan + whether mitigated
        try:
            import lessons as LZ
            present = set(res["subsystems"]) | {i["capability"] for i in res["parts"].values()}
            ls = LZ.relevant_to(present, pattern.get("extends_chain", []),
                                domain.get("extends_chain", []) if domain else [], stage)
            if ls:
                print(f"  lessons from past builds ({len(ls)}):")
                for L in ls:
                    mit = L.get("mitigation")
                    if mit and mit not in present:
                        print(f"    {L['id']}: {L['title']}  ⚠ mitigation '{mit}' NOT in plan")
                    elif mit:
                        print(f"    {L['id']}: {L['title']}  ✓ mitigation '{mit}' present")
                    else:
                        print(f"    {L['id']}: {L['title']}")
        except Exception:
            pass

    if res["unknown"]:
        # Honest: a dangling capability means the plan is incomplete.
        print("\nNOTE: unresolved capabilities above are not in the graph — "
              "fix the pattern/domain or add the capability before relying on this plan.")

    if out:
        import assemble  # shared copy routine
        notes = ""
        if domain:
            notes = f"Domain: **{domain.get('label', domain_name)}**. See DOMAIN.md for entities/workflows to scaffold."
        summary = assemble.assemble_parts(
            list(res["parts"].keys()), out,
            name=f"{pattern_name}" + (f"+{domain_name}" if domain_name else ""),
            description=pattern.get("description", ""), extra_notes=notes,
        )
        if domain:
            write_domain_md(out, domain)
        present = set(res["subsystems"]) | {i["capability"] for i in res["parts"].values()}
        comps = applicable_compositions(present)
        if comps:
            write_compositions_md(out, comps)
        try:
            import lessons as LZ
            present = set(res["subsystems"]) | {i["capability"] for i in res["parts"].values()}
            ls = LZ.relevant_to(present, pattern.get("extends_chain", []),
                                domain.get("extends_chain", []) if domain else [], stage)
            if ls:
                with open(os.path.join(out, "LESSONS.md"), "w", encoding="utf-8") as f:
                    f.write("# Lessons from past builds — apply these\n\n")
                    for L in ls:
                        f.write(f"## {L['id']} — {L['title']}\n")
                        f.write(f"**Problem:** {L['problem']}\n\n**Fix:** {L['fix']}\n\n")
        except Exception:
            ls = []
        print(f"\nmaterialized -> {out}  ({len(summary['copied'])} parts, "
              f"{len(summary['deps'])} py deps"
              + (f", {len(summary['missing'])} MISSING" if summary["missing"] else "")
              + (", +DOMAIN.md" if domain else "")
              + (f", +COMPOSITIONS.md ({len(comps)})" if comps else "")
              + (f", +LESSONS.md ({len(ls)})" if ls else "") + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
