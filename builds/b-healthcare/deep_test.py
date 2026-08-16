"""Build B (healthcare) deep validation: encrypted PHI at rest, audit trail,
log hygiene, ownership, export/erasure. App live on :8111."""
import json, os, sqlite3, sys
import httpx

BASE = "http://127.0.0.1:8111"
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "app", "app.db")
MRN = "MRN-SECRET-884213-ZQ"
results = []

def check(name, ok, detail=""):
    results.append({"name": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" -- {detail}"))

def login(email):
    c = httpx.Client(base_url=BASE, timeout=20)
    c.post("/auth/register", json={"email": email, "password": "CorrectHorse9!x"})
    r = c.post("/auth/login", json={"email": email, "password": "CorrectHorse9!x"})
    tok = r.json().get("session")
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Session": tok})
    return c

A = login("dr.adams@clinic.example")
B = login("dr.baker@clinic.example")

# patient with encrypted MRN, owner-scoped, audited
rp = A.post("/patients", json={"name": "Pat Doe", "mrn": MRN, "dob": "1980-01-02"})
check("patient create", rp.status_code == 201, rp.text[:200])
pid = rp.json().get("id")
check("owner reads decrypted MRN", MRN in A.get(f"/patients/{pid}").text)
check("B blocked from A's patient", B.get(f"/patients/{pid}").status_code in (403, 404))
check("anon blocked", httpx.get(f"{BASE}/patients").status_code == 401)

raw = open(DB, "rb").read()
check("MRN encrypted at rest", MRN.encode() not in raw)

log = open(os.path.join(HERE, "boot.log"), encoding="utf-8", errors="ignore").read()
check("MRN absent from logs", "884213-ZQ" not in log)

# audit trail: patient create audited, no PHI leak in audit
con = sqlite3.connect(DB)
audit = list(con.execute("SELECT * FROM audit_logs"))
blob = json.dumps([[str(c) for c in r] for r in audit])
check("audit rows exist", len(audit) > 0, len(audit))
check("audit covers patient create", "patient" in blob.lower() and "create" in blob.lower())
check("audit does not contain MRN", "884213-ZQ" not in blob)

# update + delete audited
A.put(f"/patients/{pid}", json={"name": "Pat D.", "mrn": MRN, "dob": "1980-01-02"})
A.delete(f"/patients/{pid}")
audit2 = list(con.execute("SELECT * FROM audit_logs"))
blob2 = json.dumps([[str(c) for c in r] for r in audit2])
check("update+delete audited", "update" in blob2.lower() and "delete" in blob2.lower(),
      f"{len(audit2)} rows")

# appointment scheduling flow (shared entity)
prov = A.post("/providers", json={"name": "Dr House", "specialty": "diagnostics"})
prid = prov.json().get("id") if prov.status_code == 201 else None
p2 = A.post("/patients", json={"name": "Second Pt", "mrn": "MRN-2", "dob": "1990-05-05"}).json()
ra = A.post("/appointments", json={"patient_id": p2["id"], "provider_id": prid,
                                   "scheduled_at": 1755400000, "reason": "checkup"})
check("appointment create", ra.status_code == 201, ra.text[:150])

# export + erasure
rx = A.get("/privacy/export")
check("export includes patient data", rx.status_code == 200 and "MRN-2" in rx.text, rx.status_code)
check("export redacts password hash", "argon2" not in rx.text)
atok = A.headers.get("X-Session", "")
check("export redacts live session token", atok not in rx.text)
rd = A.post("/privacy/delete-account")
check("delete-account", rd.status_code == 200, rd.text[:150])
check("session revoked", A.get("/auth/me").status_code == 401)
relog = httpx.post(f"{BASE}/auth/login", json={"email": "dr.adams@clinic.example", "password": "CorrectHorse9!x"})
check("erased account cannot re-login", relog.status_code == 401, relog.status_code)
check("B unaffected", B.get("/auth/me").status_code == 200)

passed = sum(1 for r in results if r["ok"])
json.dump({"passed": passed, "failed": len(results) - passed, "checks": results},
          open(os.path.join(HERE, "deep_results.json"), "w"), indent=1)
print(f"DEEP: {passed}/{len(results)}")
sys.exit(0 if passed == len(results) else 1)
