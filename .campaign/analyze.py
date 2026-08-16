"""Adjudicate smoke results against each build's DECLARED per-entity policy
(build_report.json). Reclassifies ownership/anon 'failures' that match the
declared policy; what remains are true failures. Writes adjudicated.json."""
import json, os, re, sys

def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def adjudicate(build_dir):
    smoke_p = os.path.join(build_dir, "smoke_results.json")
    rep_p = os.path.join(build_dir, "app", "build_report.json")
    if not (os.path.exists(smoke_p) and os.path.exists(rep_p)):
        return None
    smoke, rep = load(smoke_p), load(rep_p)
    by_table = {}
    for e in rep.get("entities", []):
        sec = e.get("security", {})
        by_table[e.get("table", "")] = sec
        by_table["app_" + e.get("table", "")] = sec
    out = []
    for c in smoke["checks"]:
        name, ok = c["name"], c["ok"]
        verdict = "pass" if ok else "FAIL"
        m = re.search(r"(?:ownership[^/]*|anon[^/]*)/(\w+)$", name)
        if m:
            table = m.group(1)
            sec = by_table.get(table) or by_table.get("app_" + table)
            if sec is not None:
                owner = bool(sec.get("owner_scoped_by"))
                auth = bool(sec.get("auth_required"))
                if name.startswith("ownership") and not ok and not owner:
                    verdict = "pass-per-policy(shared)"
                if "anon" in name and not ok:
                    st = c.get("detail", "")
                    if auth and st in ("401", "403"):
                        verdict = "pass-per-policy(auth-required)"
                    if not auth and st == "200":
                        verdict = "pass-per-policy(public)"
        out.append({**c, "verdict": verdict})
    true_fail = [c for c in out if c["verdict"] == "FAIL"]
    result = {"build": os.path.basename(build_dir),
              "raw": f"{smoke['passed']}/{smoke['passed']+smoke['failed']}",
              "true_failures": len(true_fail),
              "failures": [{"name": c["name"], "detail": c["detail"]} for c in true_fail],
              "checks": out}
    json.dump(result, open(os.path.join(build_dir, "adjudicated.json"), "w"), indent=1)
    return result

if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "builds"
    for b in sorted(os.listdir(root)):
        bd = os.path.join(root, b)
        if not os.path.isdir(bd):
            continue
        r = adjudicate(bd)
        if r:
            print(f"{r['build']:20} raw={r['raw']:8} true_failures={r['true_failures']}")
            for f in r["failures"]:
                print(f"    !! {f['name']} -- {f['detail'][:120]}")
