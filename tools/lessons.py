#!/usr/bin/env python3
"""
lessons.py — the feedback loop.

Build something, learn something, write it down so the next assembly benefits.
Lessons are tagged to what they apply to (patterns, domains, capabilities,
compositions, stages). The resolver surfaces the relevant ones when you plan a
matching app, so hard-won knowledge stops evaporating between builds.

    python tools/lessons.py record --title "..." --problem "..." --fix "..." \
        [--patterns a,b] [--domains a,b] [--caps a,b] [--compositions a,b] [--stages a,b]
    python tools/lessons.py list [--pattern X | --domain Y | --cap Z]
    python tools/lessons.py relevant <pattern> [--domain d] [--stage s]

This deliberately does NOT silently rewrite composition rules or stages — a
lesson is surfaced for a human/AI to act on, and can then be *promoted* by hand
into a composition recipe or a stage change. Auto-mutating the rules from
unverified field reports would be the opposite of the integrity the rest of the
system keeps.
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LDIR = os.path.join(ROOT, "lessons")
LFILE = os.path.join(LDIR, "lessons.jsonl")


def load() -> list[dict]:
    if not os.path.exists(LFILE):
        return []
    out = []
    for line in open(LFILE, encoding="utf-8"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _csv(argv, flag) -> list[str]:
    if flag in argv:
        return [x.strip() for x in argv[argv.index(flag) + 1].split(",") if x.strip()]
    return []


def _val(argv, flag) -> str:
    return argv[argv.index(flag) + 1] if flag in argv else ""


def record(argv) -> int:
    os.makedirs(LDIR, exist_ok=True)
    existing = load()
    lesson = {
        "id": "L" + str(len(existing) + 1).zfill(3),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": _val(argv, "--title"),
        "problem": _val(argv, "--problem"),
        "fix": _val(argv, "--fix"),
        "applies_to": {
            "patterns": _csv(argv, "--patterns"),
            "domains": _csv(argv, "--domains"),
            "capabilities": _csv(argv, "--caps"),
            "compositions": _csv(argv, "--compositions"),
            "stages": _csv(argv, "--stages"),
        },
        "status": "open",
    }
    if not lesson["title"]:
        print("need --title")
        return 2
    with open(LFILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(lesson) + "\n")
    print(f"recorded {lesson['id']}: {lesson['title']}")
    return 0


def relevant_to(present_caps: set[str], pattern_chain: list[str],
                domain_chain: list[str], stage: str | None) -> list[dict]:
    hits = []
    pset, dset = set(pattern_chain or []), set(domain_chain or [])
    for L in load():
        a = L["applies_to"]
        if (pset & set(a.get("patterns", []))
                or dset & set(a.get("domains", []))
                or present_caps & set(a.get("capabilities", []))
                or (stage and stage in a.get("stages", []))):
            hits.append(L)
    return hits


def cmd_list(argv) -> int:
    lessons = load()
    pat, dom, cap = _val(argv, "--pattern"), _val(argv, "--domain"), _val(argv, "--cap")
    for L in lessons:
        a = L["applies_to"]
        if pat and pat not in a.get("patterns", []):
            continue
        if dom and dom not in a.get("domains", []):
            continue
        if cap and cap not in a.get("capabilities", []):
            continue
        tags = ",".join(t for k in a for t in a[k])
        print(f"{L['id']}  {L['title']}")
        print(f"      problem: {L['problem']}")
        print(f"      fix:     {L['fix']}")
        print(f"      applies: {tags}")
    if not lessons:
        print("no lessons recorded yet")
    return 0


def cmd_relevant(argv) -> int:
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import resolve as R
    pattern_name = argv[1]
    domain_name = _val(argv, "--domain") or None
    stage = _val(argv, "--stage") or None
    graph = R.load_graph()
    pattern = R.load_pattern(pattern_name)
    if not pattern:
        print(f"unknown pattern: {pattern_name}")
        return 1
    wanted = list(pattern["requires"])
    dchain = []
    if domain_name:
        dom = R.load_domain(domain_name)
        if dom:
            wanted += dom.get("capability_hints", [])
            dchain = dom.get("extends_chain", [])
    res = R.resolve_capabilities(graph, wanted)
    present = set(res["subsystems"]) | {i["capability"] for i in res["parts"].values()}
    hits = relevant_to(present, pattern.get("extends_chain", []), dchain, stage)
    print(f"{len(hits)} lessons relevant to {pattern_name}"
          + (f"+{domain_name}" if domain_name else "") + ":")
    for L in hits:
        print(f"  {L['id']}  {L['title']} — {L['fix']}")
    return 0


PROMOTIONS = os.path.join(LDIR, "promotions.jsonl")
PROMOTION_TARGETS = ["validation_rule", "composition_rule", "alternative_score",
                     "operational_profile", "fitness_rule", "documentation_note", "part_update"]
LESSON_STATUSES = ["open", "reviewed", "accepted", "promoted", "rejected", "deprecated"]


def _rewrite(lessons):
    with open(LFILE, "w", encoding="utf-8") as f:
        for L in lessons:
            f.write(json.dumps(L) + "\n")


def review(argv) -> int:
    lid = argv[1] if len(argv) > 1 else ""
    status = _val(argv, "--status") or "reviewed"
    if status not in LESSON_STATUSES:
        print(f"status must be one of {LESSON_STATUSES}"); return 2
    lessons = load()
    found = False
    for L in lessons:
        if L["id"] == lid:
            L["status"] = status
            found = True
    if not found:
        print(f"no such lesson: {lid}"); return 1
    _rewrite(lessons)
    print(f"{lid} -> {status}")
    return 0


def promote(argv) -> int:
    """Promote a lesson into a durable rule. Requires an explicit target + reason;
    records the intent in promotions.jsonl. Does NOT silently mutate the rule
    files — a human/AI still writes the rule, then references this promotion."""
    lid = argv[1] if len(argv) > 1 else ""
    target = _val(argv, "--target")
    reason = _val(argv, "--reason")
    if target not in PROMOTION_TARGETS:
        print(f"--target must be one of {PROMOTION_TARGETS}"); return 2
    if not reason:
        print("need --reason (why this lesson should become a rule)"); return 2
    lessons = load()
    match = next((L for L in lessons if L["id"] == lid), None)
    if not match:
        print(f"no such lesson: {lid}"); return 1
    match["status"] = "promoted"
    _rewrite(lessons)
    rec = {"lesson_id": lid, "target": target, "reason": reason,
           "created_at": datetime.now(timezone.utc).isoformat(), "applied": False}
    with open(PROMOTIONS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"promoted {lid} -> {target}: {reason}")
    print("  (now write the rule and set 'applied': true in promotions.jsonl)")
    return 0


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "record":
        return record(argv)
    if argv[0] == "list":
        return cmd_list(argv)
    if argv[0] == "relevant" and len(argv) >= 2:
        return cmd_relevant(argv)
    if argv[0] == "review":
        return review(argv)
    if argv[0] == "promote":
        return promote(argv)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
