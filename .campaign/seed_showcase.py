"""Seed all 4 showcase apps with believable stories + screenshot the journeys.
Run after showcase_batch.sh. Boots each app, seeds via its real HTTP API,
drives the actual UI in headless Chrome, saves screenshots + artifacts."""
import os, subprocess as sp, sys, time
import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
ENV = dict(os.environ)
ENV["PQ_FIELD_PUBLIC"] = open("builds/.showcase_pq_public.key").read().strip()
ENV["PQ_FIELD_SECRET"] = open("builds/.showcase_pq_secret.key").read().strip()
PW = "CorrectHorse9!x"
SHOTS = "C:/tmp/showcase"
os.makedirs(SHOTS, exist_ok=True)

def boot(build, port):
    p = sp.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
                 cwd=f"builds/{build}/app", env=ENV, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    for _ in range(40):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=2).status_code == 200:
                return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"{build} did not boot")

def client(port, email):
    c = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=25)
    c.post("/auth/register", json={"email": email, "password": PW})
    tok = c.post("/auth/login", json={"email": email, "password": PW}).json()["session"]
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Session": tok})
    return c

def must(r, what):
    assert r.status_code in (200, 201), f"{what}: {r.status_code} {r.text[:200]}"
    return r.json() if r.text else {}

def trans(c, coll, rid, to):
    must(c.post(f"/{coll}/{rid}/transition", json={"to": to}), f"{coll}#{rid}->{to}")

# ---------------- Overturn ----------------
def seed_overturn(c):
    cl = must(c.post("/claims", json={"insurer": "BlueCare PPO", "claim_number": "BC-2026-118842",
        "service": "Lumbar MRI", "provider": "Riverside Imaging", "service_date": "2026-05-14T09:00:00Z",
        "billed_cents": 234000}), "claim")
    cid = cl["id"]
    trans(c, "claims", cid, "denied")
    must(c.post("/denials", json={"claim_id": cid, "denial_date": "2026-06-02T00:00:00Z",
        "reason_code": "CO-50", "reason_text": "Not medically necessary per plan criteria",
        "internal_appeal_deadline": "2026-12-02T00:00:00Z",
        "external_review_deadline": "2027-04-02T00:00:00Z"}), "denial")
    for kind, title, body, at in [
        ("physician_letter", "Letter of medical necessity — Dr. Okafor",
         "Six weeks of conservative treatment failed; radiculopathy symptoms progressing. MRI is the standard of care per ACR guidelines.", "2026-06-10T00:00:00Z"),
        ("plan_document", "Plan clause 4.2.1 — imaging coverage",
         "Advanced imaging is covered when conservative treatment has failed for 4+ weeks. My records show 6 weeks.", "2026-06-11T00:00:00Z"),
        ("medical_record", "PT discharge summary",
         "Physical therapy 4/2-5/12, discharged with 'no improvement, recommend advanced imaging'.", "2026-06-12T00:00:00Z")]:
        must(c.post("/evidence_items", json={"claim_id": cid, "kind": kind, "title": title,
                                             "body": body, "received_at": at}), "evidence")
    must(c.post("/call_logs", json={"claim_id": cid, "called_at": "2026-06-05T14:30:00Z",
        "rep_name": "Marcus", "reference_number": "REF-88123",
        "summary": "Confirmed denial reason code CO-50; rep stated appeal must cite plan clause 4.2.1."}), "call")
    must(c.post("/call_logs", json={"claim_id": cid, "called_at": "2026-06-18T10:05:00Z",
        "rep_name": "Dana", "reference_number": "REF-90477",
        "summary": "Confirmed appeal packet received 6/17; 30-day review clock started."}), "call")
    trans(c, "claims", cid, "internal_appeal")
    ap = must(c.post("/appeals", json={"claim_id": cid, "level": "internal",
        "filed_at": "2026-06-17T00:00:00Z",
        "argument": "Denial cites medical necessity, but plan clause 4.2.1 covers advanced imaging after 4+ weeks failed conservative treatment. Enclosed: PT discharge summary (6 weeks, no improvement) and physician letter."}), "appeal")
    trans(c, "appeals", ap["id"], "filed")
    trans(c, "appeals", ap["id"], "won")
    trans(c, "claims", cid, "overturned")
    trans(c, "claims", cid, "paid")
    # second claim mid-fight
    cl2 = must(c.post("/claims", json={"insurer": "BlueCare PPO", "claim_number": "BC-2026-120913",
        "service": "Physical therapy x12", "provider": "Motion Health", "service_date": "2026-07-01T00:00:00Z",
        "billed_cents": 96000}), "claim2")
    trans(c, "claims", cl2["id"], "denied")
    must(c.post("/denials", json={"claim_id": cl2["id"], "denial_date": "2026-08-01T00:00:00Z",
        "reason_code": "CO-197", "reason_text": "Prior authorization absent",
        "internal_appeal_deadline": "2027-02-01T00:00:00Z",
        "external_review_deadline": "2027-06-01T00:00:00Z"}), "denial2")
    must(c.post("/appeals", json={"claim_id": cl2["id"], "level": "internal",
        "filed_at": "2026-08-15T00:00:00Z",
        "argument": "Prior auth WAS obtained 6/24 (auth #A-55871, confirmed by rep). Drafting."}), "appeal2")
    return cid

# ---------------- Deposit Shield ----------------
def seed_deposit(c):
    t = must(c.post("/tenancies", json={"address": "412 Maple St, Apt 3B", "landlord": "Crestview Property Mgmt",
        "deposit_cents": 180000, "move_in": "2025-08-01T00:00:00Z", "move_out": "2026-07-31T00:00:00Z",
        "return_deadline_days": 30}), "tenancy")
    tid = t["id"]
    shots = [
        ("move_in", "kitchen", "IMG_0114.jpg", "Counters unmarked, appliances clean, small existing chip on sink edge noted"),
        ("move_in", "carpet", "IMG_0117.jpg", "Living-room carpet: existing wear path by door, photographed on day one"),
        ("move_in", "bathroom", "IMG_0121.jpg", "Grout dingy at move-in — pre-existing"),
        ("move_out", "kitchen", "IMG_2201.jpg", "Counters wiped, appliances degreased, same sink chip"),
        ("move_out", "carpet", "IMG_2205.jpg", "Carpet professionally cleaned 7/29 (receipt kept), same wear path"),
        ("move_out", "bathroom", "IMG_2210.jpg", "Bathroom scrubbed; grout condition unchanged from move-in photo"),
    ]
    for phase, room, ref, note in shots:
        at = "2025-08-01T10:00:00Z" if phase == "move_in" else "2026-07-30T17:00:00Z"
        must(c.post("/evidence_shots", json={"tenancy_id": tid, "phase": phase, "room": room,
            "photo_ref": ref, "condition_note": note, "taken_at": at}), "shot")
    trans(c, "tenancies", tid, "notice_given")
    trans(c, "tenancies", tid, "moved_out")
    trans(c, "tenancies", tid, "deductions_received")
    for cents, reason in [(45000, "carpet replacement"), (25000, "deep cleaning kitchen"),
                          (30000, "bathroom regrouting")]:
        must(c.post("/deductions", json={"tenancy_id": tid, "amount_cents": cents,
                                         "landlord_reason": reason}), "deduction")
    trans(c, "tenancies", tid, "disputing")
    return tid

# ---------------- The Binder ----------------
def seed_binder(c):
    ch = must(c.post("/children", json={"first_name": "E.", "grade": "4th", "school": "Lincoln Elementary",
        "plan_type": "IEP", "diagnosis": "Dyslexia; ADHD combined type",
        "notes": "Responds well to structured literacy. Needs movement breaks.",
        "promised_minutes_week": 120}), "child")
    kid = ch["id"]
    m1 = must(c.post("/meetings", json={"child_id": kid, "kind": "Annual IEP",
        "held_at": "2026-05-08T14:00:00Z", "attendees": "Parent, case manager, sped teacher, principal designee",
        "notes": "Agreed: 120 min/wk structured literacy, movement breaks, extended time. Minutes promised within 10 days."}), "m1")
    for to in ("scheduled", "held", "minutes_received"): trans(c, "meetings", m1["id"], to)
    m2 = must(c.post("/meetings", json={"child_id": kid, "kind": "Progress review",
        "held_at": "2026-09-15T14:00:00Z", "attendees": "Requested: parent, case manager",
        "notes": "Requested in writing 8/10 after service shortfall appeared in the log."}), "m2")
    trans(c, "meetings", m2["id"], "scheduled")
    for direction, who, ch_, at, subj, body in [
        ("out", "Case manager", "email", "2026-08-10T08:30:00Z", "Service delivery concern",
         "Per my log, E. received 60 of 120 promised minutes for two consecutive weeks. Requesting a progress review and written explanation."),
        ("in", "Case manager", "email", "2026-08-12T15:10:00Z", "RE: Service delivery concern",
         "Staffing shortage acknowledged; review scheduled 9/15. Missed minutes to be compensated."),
        ("out", "Principal", "email", "2026-08-13T09:00:00Z", "Compensatory services confirmation",
         "Please confirm in writing the compensatory minutes plan discussed.")]:
        must(c.post("/correspondences", json={"child_id": kid, "direction": direction, "with_whom": who,
            "channel": ch_, "sent_at": at, "subject": subj, "body": body}), "corr")
    for week, minutes, delivered in [("2026-07-27", 120, True), ("2026-08-03", 60, True),
                                     ("2026-08-10", 60, True), ("2026-08-17", 0, False)]:
        must(c.post("/service_entries", json={"child_id": kid, "service": "Structured literacy",
            "minutes": minutes, "delivered_at": week + "T00:00:00Z", "delivered": delivered}), "svc")
    a1 = must(c.post("/action_items", json={"child_id": kid, "owner": "School",
        "description": "Provide written compensatory-minutes plan", "due_at": "2026-08-20T00:00:00Z"}), "a1")
    trans(c, "action_items", a1["id"], "overdue")
    must(c.post("/action_items", json={"child_id": kid, "owner": "Parent",
        "description": "Bring service-delivery log to 9/15 review", "due_at": "2026-09-15T00:00:00Z"}), "a2")

# ---------------- Care Circle ----------------
def seed_care(c):
    r = must(c.post("/care_recipients", json={"name": "Elena (Mom)", "lives_at": "Home — Cedar Falls",
        "primary_doctor": "Dr. Reyes (family med)", "emergency_contact": "Ana 555-0141"}), "recipient")
    rid = r["id"]
    m1 = must(c.post("/medications", json={"recipient_id": rid, "name": "Metformin", "dose": "500mg",
        "schedule": "twice daily with meals", "prescriber": "Dr. Reyes"}), "med1")
    m2 = must(c.post("/medications", json={"recipient_id": rid, "name": "Lisinopril", "dose": "10mg",
        "schedule": "morning", "prescriber": "Dr. Reyes"}), "med2")
    for med, at, by in [(m1["id"], "2026-08-16T08:05:00Z", "Ana"), (m2["id"], "2026-08-16T08:05:00Z", "Ana"),
                        (m1["id"], "2026-08-15T19:20:00Z", "Luis")]:
        must(c.post("/dose_logs", json={"medication_id": med, "given_at": at, "given_by": by,
                                        "taken": True, "note": "no issues"}), "dose")
    ap = must(c.post("/appointments", json={"recipient_id": rid, "with_whom": "Cardiology — Dr. Behm",
        "at": "2026-08-22T10:30:00Z", "driver": "Sam", "outcome_note": ""}), "appt")
    t1 = must(c.post("/care_tasks", json={"recipient_id": rid, "title": "Groceries + refill pillbox",
        "assigned_to": "", "due_at": "2026-08-17T12:00:00Z"}), "t1")
    trans(c, "care_tasks", t1["id"], "claimed")
    must(c.post("/care_tasks", json={"recipient_id": rid, "title": "Install grab bar in shower",
        "assigned_to": "", "due_at": "2026-08-24T00:00:00Z"}), "t2")
    t3 = must(c.post("/care_tasks", json={"recipient_id": rid, "title": "Call insurance re: walker coverage",
        "assigned_to": "", "due_at": "2026-08-14T00:00:00Z"}), "t3")
    trans(c, "care_tasks", t3["id"], "claimed")
    trans(c, "care_tasks", t3["id"], "missed")
    trans(c, "care_tasks", t3["id"], "escalated")
    for author, at, body in [
        ("Ana", "2026-08-16T08:30:00Z", "Morning meds done, she's in good spirits. Asked about Sam's visit Saturday."),
        ("Luis", "2026-08-15T19:40:00Z", "Evening check-in fine. BP 132/84. She wants tamales for Sunday."),
    ]:
        must(c.post("/updates", json={"recipient_id": rid, "author": author, "posted_at": at, "body": body}), "upd")

APPS = [("sc-overturn", 8151, "maria@overturn.example", seed_overturn),
        ("sc-deposit", 8152, "jess@depositshield.example", seed_deposit),
        ("sc-binder", 8153, "parent@binder.example", seed_binder),
        ("sc-care", 8154, "ana@carecircle.example", seed_care)]

if __name__ == "__main__":
    procs = []
    try:
        for build, port, email, seeder in APPS:
            dbp = f"builds/{build}/app/app.db"
            if os.path.exists(dbp): os.remove(dbp)
            procs.append(boot(build, port))
            c = client(port, email)
            seeder(c)
            print(f"seeded {build}")
        # artifacts from the custom glue
        c = client(8151, "maria@overturn.example")
        open(f"{SHOTS}/overturn_packet.txt", "w", encoding="utf-8").write(c.get("/packet/1").text)
        c = client(8152, "jess@depositshield.example")
        open(f"{SHOTS}/deposit_letter.txt", "w", encoding="utf-8").write(c.get("/letter/1").text)
        print("artifacts written")
        # UI screenshots: login -> dashboard -> key entity for each app
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        opts = Options()
        for a in ("--headless=new", "--no-sandbox", "--disable-gpu", "--window-size=1440,900"):
            opts.add_argument(a)
        d = webdriver.Chrome(options=opts)
        FOCUS = {"sc-overturn": "claims", "sc-deposit": "evidence shots",
                 "sc-binder": "service entries", "sc-care": "care tasks"}
        for build, port, email, _ in APPS:
            d.get(f"http://127.0.0.1:{port}/app/")
            time.sleep(1.6)
            d.save_screenshot(f"{SHOTS}/{build}_1_landing.png")
            d.find_element(By.ID, "email").send_keys(email)
            d.find_element(By.ID, "pw").send_keys(PW)
            d.find_element(By.ID, "go").click()
            time.sleep(2.5)
            d.save_screenshot(f"{SHOTS}/{build}_2_dashboard.png")
            for a in d.find_elements(By.CSS_SELECTOR, ".sidenav a"):
                if a.text.strip().lower() == FOCUS[build]:
                    a.click(); break
            time.sleep(1.6)
            d.save_screenshot(f"{SHOTS}/{build}_3_records.png")
            print(f"shot {build}")
        d.quit()
    finally:
        for p in procs: p.terminate()
    print("SEED+SHOOT DONE")
