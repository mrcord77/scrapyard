"""
gen_probe_metadata.py — exercise every resource entity of a generated app over HTTP
and write a per-entity metadata of exactly what was probed and what happened.

Unlike the aggregate runtime check (one pass/fail), this records, per entity, the
create/read/update/delete (+ workflow transition) attempts with status codes, so
verification is auditable entity-by-entity. Writes into the app dir:
  probe_metadata.json   machine-readable per-entity results
  PROBE_METADATA.md     human-readable

Usage:  python tools/gen_probe_metadata.py <generated_app_dir>
Boots main:app in a clean subprocess (PYTHONPATH = app dir) — no server needed.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys


def _probe(app_dir: str) -> dict:
    code = r'''
import json, os, sys, importlib.util, traceback
res = {"entities": [], "auth": None}
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///./_probe_metadata.db")
os.environ.setdefault("SECRET_KEY", "probe-metadata-secret-000000")
if "PQ_FIELD_PUBLIC" not in os.environ:
    try:
        from scrapyard.security.pq_field_encryption import generate_recipient_hex
        pk, sk = generate_recipient_hex()
        os.environ["PQ_FIELD_PUBLIC"] = pk; os.environ["PQ_FIELD_SECRET"] = sk
    except Exception:
        pass
try:
    spec = importlib.util.spec_from_file_location("genmain", os.path.join(os.getcwd(), "main.py"))
    m = importlib.util.module_from_spec(spec); sys.modules["genmain"] = m; spec.loader.exec_module(m)
    from fastapi.testclient import TestClient
    c = TestClient(m.app)
    schema = c.get("/openapi.json").json()
    paths = schema.get("paths", {})

    # authenticate if the app has an auth surface; elevate so role-gated writes are exercised
    headers = {}
    if "/auth/register" in paths and "/auth/login" in paths:
        c.post("/auth/register", json={"email": "probe@x.co", "password": "S3curePass!"})
        login = c.post("/auth/login", json={"email": "probe@x.co", "password": "S3curePass!"})
        if login.status_code == 200 and "session" in login.json():
            sess = login.json()["session"]; headers = {"X-Session": sess}
            res["auth"] = "session"
            try:
                from scrapyard.database.db_session import session_scope
                from scrapyard.identity.session_manager import SessionManager
                from scrapyard.authorization.roles import grant
                with session_scope() as db:
                    uid = SessionManager(db).user_id_for(sess)
                    grant(db, uid, "admin"); grant(db, uid, "owner")
                res["auth"] = "session+admin"
            except Exception:
                pass

    def infra(p):
        return (p in ("/health","/healthz","/livez","/readyz","/openapi.json","/docs","/redoc","/capabilities","/")
                or p.startswith("/auth") or p.startswith("/privacy"))

    def required_body(path):
        try:
            ref = paths[path]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            comp = schema["components"]["schemas"][ref.split("/")[-1]]
            return comp.get("properties", {}), set(comp.get("required", []))
        except Exception:
            return {}, set()

    def sample(props, required):
        b = {}
        for f, spec in props.items():
            if f == "id" or f not in required:
                continue
            t = spec.get("type", "string")
            b[f] = 1 if t in ("integer", "number") else (True if t == "boolean" else "x")
        return b

    # resource entities: a collection POST that has an item sub-route ({id})
    collections = sorted({p for p in paths if not infra(p)
                          and "post" in paths[p]
                          and any(q.startswith(p + "/{") for q in paths)})
    for path in collections:
        item = next((q for q in paths if q.startswith(path + "/{") and "{" in q and "/transition" not in q), None)
        transition = next((q for q in paths if q.startswith(path + "/{") and q.endswith("/transition")), None)
        ops = []
        props, required = required_body(path)
        cr = c.post(path, json=sample(props, required), headers=headers)
        ops.append({"op": "create", "method": "POST", "path": path, "status": cr.status_code,
                    "ok": cr.status_code in (200, 201)})
        rid = cr.json().get("id") if cr.status_code in (200, 201) and isinstance(cr.json(), dict) else None
        if rid is not None and item:
            ip = item.replace("{id_}", str(rid)).replace("{id}", str(rid))
            gr = c.get(ip, headers=headers)
            ops.append({"op": "read", "method": "GET", "path": ip, "status": gr.status_code, "ok": gr.status_code == 200})
            if item in paths and "put" in paths.get(item, {}):
                ur = c.put(ip, json={}, headers=headers)
                ops.append({"op": "update", "method": "PUT", "path": ip, "status": ur.status_code, "ok": ur.status_code == 200})
            if transition:
                tp = transition.replace("{id_}", str(rid)).replace("{id}", str(rid))
                tr = c.post(tp, json={"to": "__invalid__"}, headers=headers)
                # an invalid transition should be rejected (409) — proves the gate is live
                ops.append({"op": "transition_guard", "method": "POST", "path": tp, "status": tr.status_code,
                            "ok": tr.status_code in (409, 422)})
            if item in paths and "delete" in paths.get(item, {}):
                dr = c.delete(ip, headers=headers)
                gone = dr.status_code in (200, 204)
                ops.append({"op": "delete", "method": "DELETE", "path": ip, "status": dr.status_code, "ok": gone})
        res["entities"].append({"collection": path, "operations": ops,
                                "ok": all(o["ok"] for o in ops)})
except Exception:
    res["error"] = traceback.format_exc().splitlines()[-1]
print("METADATA=" + json.dumps(res))
'''
    env = dict(os.environ, PYTHONPATH=app_dir)
    env.pop("DATABASE_URL", None)
    p = subprocess.run([sys.executable, "-c", code], cwd=app_dir, env=env, capture_output=True, text=True)
    line = next((l for l in p.stdout.splitlines() if l.startswith("METADATA=")), None)
    if not line:
        return {"error": (p.stderr.strip().splitlines() or ["no output"])[-1]}
    return json.loads(line.split("=", 1)[1])


def to_markdown(rep: dict) -> str:
    L = ["# Probe metadata", "",
         "_Per-entity record of what the runtime verifier exercised over HTTP._", "",
         f"Auth: **{rep.get('auth') or 'none'}**.", ""]
    if rep.get("error"):
        L += [f"> probe error: {rep['error']}", ""]
    total_ok = sum(1 for e in rep.get("entities", []) if e["ok"])
    L += [f"Entities probed: **{len(rep.get('entities', []))}** · fully green: **{total_ok}**.", ""]
    for e in rep.get("entities", []):
        L.append(f"### `{e['collection']}` — {'PASS' if e['ok'] else 'FAIL'}")
        for o in e["operations"]:
            mark = "ok" if o["ok"] else "FAIL"
            L.append(f"- {o['op']}: `{o['method']} {o['path']}` -> {o['status']} ({mark})")
        L.append("")
    return "\n".join(L)


def write_metadata(app_dir: str) -> dict:
    rep = _probe(app_dir)
    with open(os.path.join(app_dir, "probe_metadata.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2)
    with open(os.path.join(app_dir, "PROBE_METADATA.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(rep))
    return rep


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python tools/gen_probe_metadata.py <generated_app_dir>")
        return 2
    app_dir = os.path.abspath(argv[0])
    if not os.path.isdir(app_dir):
        print(f"not a directory: {app_dir}")
        return 2
    rep = write_metadata(app_dir)
    if rep.get("error") and not rep.get("entities"):
        print(f"[metadata]   probe error: {rep['error']}")
        return 1
    ents = rep.get("entities", [])
    green = sum(1 for e in ents if e["ok"])
    print(f"[metadata]   {len(ents)} entit{'y' if len(ents)==1 else 'ies'} probed · {green} fully green "
          f"(auth={rep.get('auth') or 'none'}) -> PROBE_METADATA.md + probe_metadata.json")
    return 0 if green == len(ents) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
