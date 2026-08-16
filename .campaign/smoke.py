"""Generic HTTP smoke harness for Scrapyard-generated apps.

Discovers entities from the running app's /openapi.json, synthesizes minimal
valid payloads from the request schemas, then runs functional CRUD checks and
adversarial checks (ownership isolation, anon access, malformed input,
stale session). Results -> JSON file.

Usage: py smoke.py --base http://127.0.0.1:8101 --out results.json
"""
import argparse, json, sys, time
import httpx

SKIP_PREFIXES = ("/auth", "/admin", "/privacy", "/healthz", "/livez", "/app",
                 "/openapi", "/docs", "/redoc", "/metrics", "/billing")

def sample_for(prop: dict, name: str, defs: dict, depth=0):
    if "$ref" in prop:
        target = prop["$ref"].split("/")[-1]
        return sample_for(defs.get(target, {}), name, defs, depth + 1)
    if "enum" in prop:
        return prop["enum"][0]
    if "anyOf" in prop:
        for opt in prop["anyOf"]:
            if opt.get("type") != "null":
                return sample_for(opt, name, defs, depth + 1)
        return None
    t = prop.get("type")
    if t == "string":
        if prop.get("format") == "email" or "email" in name:
            return "smoke@example.com"
        if prop.get("format") in ("date-time",):
            return "2026-08-16T12:00:00Z"
        if prop.get("format") == "date":
            return "2026-08-16"
        return f"smoke-{name}"
    if t == "integer":
        return 1
    if t == "number":
        return 1.5
    if t == "boolean":
        return True
    if t == "array":
        return []
    if t == "object" or "properties" in prop:
        return {k: sample_for(v, k, defs, depth + 1)
                for k, v in prop.get("properties", {}).items()}
    return f"smoke-{name}"

def build_payload(schema_ref: str, spec: dict):
    defs = spec.get("components", {}).get("schemas", {})
    schema = defs.get(schema_ref.split("/")[-1], {})
    explicit_required = schema.get("required") or []
    out = {}
    for fname, prop in schema.get("properties", {}).items():
        if fname in ("id", "created_at", "updated_at", "owner_id", "user_id"):
            continue
        if fname in ("status", "state") and fname not in explicit_required:
            continue  # let the server apply the state-machine initial value
        out[fname] = sample_for(prop, fname, defs)
    return out

def discover_entities(spec: dict):
    ents = []
    for path, ops in spec.get("paths", {}).items():
        if path.startswith(SKIP_PREFIXES) or "{" in path:
            continue
        post = ops.get("post")
        if not post:
            continue
        body = (post.get("requestBody", {}).get("content", {})
                .get("application/json", {}).get("schema", {}))
        ref = body.get("$ref") or ""
        if not ref:
            continue  # action endpoint (e.g. /x/sweep), not entity creation
        ents.append({"collection": path, "schema_ref": ref})
    return ents

class Harness:
    def __init__(self, base, out, public_ok=False):
        self.base, self.out = base, out
        self.public_ok = public_ok  # low-sensitivity build: open CRUD is declared policy
        self.checks = []
        self.spec = None

    def check(self, name, ok, detail=""):
        self.checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f" -- {detail}" if not ok and detail else ""))

    def client(self):
        return httpx.Client(base_url=self.base, timeout=20.0, follow_redirects=True)

    def register_login(self, c, email, pw="CorrectHorse9!x"):
        r = c.post("/auth/register", json={"email": email, "password": pw})
        if r.status_code not in (200, 201, 409):
            return r
        r = c.post("/auth/login", json={"email": email, "password": pw})
        if r.status_code == 200:
            body = r.json()
            token = body.get("session") or body.get("access") or body.get("access_token")
            if token:
                c.headers["Authorization"] = f"Bearer {token}"
                c.headers["X-Session"] = token
        return r

    def run(self):
        A, B, anon = self.client(), self.client(), self.client()
        r = A.get("/healthz")
        self.check("health", r.status_code == 200, r.text)
        self.spec = A.get("/openapi.json").json()

        ra = self.register_login(A, "alice.smoke@example.com")
        self.check("register+login A", ra.status_code == 200, ra.text)
        rb = self.register_login(B, "bob.smoke@example.com")
        self.check("register+login B", rb.status_code == 200, rb.text)
        rd = A.post("/auth/register", json={"email": "alice.smoke@example.com",
                                            "password": "CorrectHorse9!x"})
        self.check("duplicate registration rejected", rd.status_code in (400, 409, 422), rd.status_code)
        rme = A.get("/auth/me")
        self.check("auth/me", rme.status_code == 200, rme.text)

        entities = discover_entities(self.spec)
        self.check("entities discovered", len(entities) > 0, f"{len(entities)}")
        created = {}  # collection -> id (owned by A)
        pending = list(entities)
        for _pass in range(4):  # FK ordering: retry deferred creates
            nxt = []
            for e in pending:
                payload = build_payload(e["schema_ref"], self.spec)
                for f in list(payload):
                    if f.endswith("_id"):
                        ref = "/" + f[:-3] + "s"
                        payload[f] = created.get(ref, 1)
                r = A.post(e["collection"], json=payload)
                if r.status_code in (200, 201):
                    body = r.json()
                    created[e["collection"]] = body.get("id", 1)
                    e["payload"] = payload
                else:
                    e["last_err"] = f"{r.status_code} {r.text[:200]}"
                    nxt.append(e)
            pending = nxt
            if not pending:
                break
        for e in entities:
            ok = e["collection"] in created
            self.check(f"create {e['collection']}", ok, e.get("last_err", ""))

        for coll, eid in created.items():
            r = A.get(f"{coll}/{eid}")
            self.check(f"read {coll}/{eid}", r.status_code == 200, r.status_code)
            rl = A.get(coll)
            self.check(f"list {coll}", rl.status_code == 200, rl.status_code)
            # ownership isolation: B must not see A's row
            rb2 = B.get(f"{coll}/{eid}")
            if self.public_ok:
                self.check(f"ownership n/a (public policy) {coll}", True, "declared public")
            else:
                self.check(f"ownership: B blocked from A's {coll}", rb2.status_code in (403, 404), rb2.status_code)
            # anon blocked
            rn = anon.get(coll)
            if self.public_ok:
                self.check(f"anon read allowed by policy {coll}", rn.status_code == 200, rn.status_code)
            else:
                self.check(f"anon blocked {coll}", rn.status_code in (401, 403), rn.status_code)

        # update + delete on first created entity
        if created:
            coll, eid = next(iter(created.items()))
            e0 = next(e for e in entities if e["collection"] == coll)
            r = A.put(f"{coll}/{eid}", json=e0.get("payload", {}))
            self.check(f"update {coll}/{eid}", r.status_code in (200, 204), f"{r.status_code} {r.text[:150]}")
            r404 = A.get(f"{coll}/999999")
            self.check("missing record -> 404", r404.status_code == 404, r404.status_code)
            rbad = A.post(coll, content=b"{not json", headers={"content-type": "application/json"})
            self.check("malformed payload rejected", rbad.status_code in (400, 422), rbad.status_code)
            rdel = A.delete(f"{coll}/{eid}")
            self.check(f"delete {coll}/{eid}", rdel.status_code in (200, 204), rdel.status_code)
            rgone = A.get(f"{coll}/{eid}")
            self.check("deleted record gone", rgone.status_code == 404, rgone.status_code)

        # stale session after logout
        rl = A.post("/auth/logout")
        self.check("logout", rl.status_code in (200, 204), rl.status_code)
        rstale = A.get("/auth/me")
        self.check("stale session rejected after logout", rstale.status_code in (401, 403), rstale.status_code)

        passed = sum(1 for c in self.checks if c["ok"])
        result = {"base": self.base, "passed": passed, "failed": len(self.checks) - passed,
                  "checks": self.checks}
        with open(self.out, "w") as f:
            json.dump(result, f, indent=1)
        print(f"SMOKE: {passed}/{len(self.checks)} passed -> {self.out}")
        return 0 if passed == len(self.checks) else 1

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", default="smoke_results.json")
    ap.add_argument("--public-ok", action="store_true",
                    help="low-sensitivity build: open CRUD is the declared policy")
    args = ap.parse_args()
    sys.exit(Harness(args.base, args.out, public_ok=args.public_ok).run())
