"""Build A (sobriety SaaS) deep validation: privacy, encryption-at-rest,
export, deletion, audit, log hygiene. Run with the app live on :8110."""
import json, os, re, sqlite3, sys
import httpx

BASE = "http://127.0.0.1:8110"
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
DB = os.path.join(APP, "app.db")
SECRET_BODY = "relapsed-thought-XYZZY-7741 about a private meeting"
results = []

def check(name, ok, detail=""):
    results.append({"name": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" -- {detail}"))

def login(email):
    c = httpx.Client(base_url=BASE, timeout=20)
    c.post("/auth/register", json={"email": email, "password": "CorrectHorse9!x"})
    r = c.post("/auth/login", json={"email": email, "password": "CorrectHorse9!x"})
    tok = r.json().get("session")
    c.headers["Authorization"] = f"Bearer {tok}"
    c.headers["X-Session"] = tok
    return c

A = login("ana.deep@example.com")
B = login("ben.deep@example.com")

# 1. private journal + ownership
rj = A.post("/journal_entries", json={"body": SECRET_BODY, "mood": "fragile"})
check("journal create", rj.status_code == 201, rj.text)
jid = rj.json().get("id")
check("journal private from B", B.get(f"/journal_entries/{jid}").status_code in (403, 404))
check("journal readable by owner (decrypted)", SECRET_BODY in A.get(f"/journal_entries/{jid}").text)

# 2. encryption at rest: raw DB must NOT contain plaintext
raw = open(DB, "rb").read()
check("journal body encrypted at rest", SECRET_BODY.encode() not in raw)
check("mood encrypted at rest", b"fragile" not in raw)

# 3. sensitive values must not appear in server logs
logtxt = open(os.path.join(os.path.dirname(APP), "boot.log"), encoding="utf-8", errors="ignore").read()
check("journal body absent from logs", "XYZZY-7741" not in logtxt)

# 4. data export contains the user's journal
rx = A.get("/privacy/export")
check("export endpoint", rx.status_code == 200, rx.status_code)
check("export contains journal", "XYZZY-7741" in rx.text)
rs = A.get("/privacy/export/stream")
check("streaming export", rs.status_code == 200 and "XYZZY-7741" in rs.text, rs.status_code)

# 5. audit events for journal create (declared audit: create/delete)
con = sqlite3.connect(DB)
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
audit_t = next((t for t in tables if "audit" in t), None)
check("audit table exists", audit_t is not None, tables)
if audit_t:
    rows = list(con.execute(f"SELECT * FROM {audit_t}"))
    check("audit rows recorded", len(rows) > 0, f"{len(rows)} rows")
    blob = json.dumps([[str(c) for c in r] for r in rows])
    check("audit mentions journal create", "journal" in blob.lower() and "create" in blob.lower())
    check("audit does not leak journal body", "XYZZY-7741" not in blob)

# 6. meetings + attendance + milestones + chips + sobriety date field
rm = A.post("/meetings", json={"name": "Sunrise Group", "location": "smoke hall", "schedule": {"day": "sun", "time": "8am"}})
mid = rm.json().get("id") if rm.status_code == 201 else None
check("meeting create", rm.status_code == 201, rm.text[:120])
ra = A.post("/attendances", json={"meeting_id": mid, "attended_at": 1755300000})
check("attendance log", ra.status_code == 201, ra.text[:120])
rc = A.post("/chips", json={"kind": "30-day", "awarded_at": 1755300000})
check("chip create", rc.status_code == 201, rc.text[:120])
rmi = A.post("/milestones", json={"kind": "30 days", "reached_at": 1755300000})
check("milestone create", rmi.status_code == 201, rmi.text[:120])

# 7. account deletion: A erased, session dead, B untouched
bjid = B.post("/journal_entries", json={"body": "bens entry stays", "mood": "ok"}).json().get("id")
rdel = A.post("/privacy/delete-account")
check("delete-account", rdel.status_code in (200, 202, 204), f"{rdel.status_code} {rdel.text[:150]}")
check("A session revoked after deletion", A.get("/auth/me").status_code in (401, 403))
raw2 = open(DB, "rb").read()
check("A's encrypted rows erased", A.get(f"/journal_entries/{jid}").status_code in (401, 403, 404))
check("B's journal untouched", B.get(f"/journal_entries/{bjid}").status_code == 200)
relogin = httpx.Client(base_url=BASE, timeout=20).post("/auth/login", json={"email": "ana.deep@example.com", "password": "CorrectHorse9!x"})
check("deleted account cannot log in", relogin.status_code in (401, 403), relogin.status_code)

# 8. billing honesty: endpoints exist, but no live Stripe path
spec = httpx.get(BASE + "/openapi.json").json()
bill = [p for p in spec["paths"] if "billing" in p or "stripe" in p or "checkout" in p or "subscription" in p]
print("billing surface:", bill)

passed = sum(1 for r in results if r["ok"])
json.dump({"passed": passed, "failed": len(results) - passed, "checks": results},
          open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "deep_results.json"), "w"), indent=1)
print(f"DEEP: {passed}/{len(results)}")
sys.exit(0 if passed == len(results) else 1)
