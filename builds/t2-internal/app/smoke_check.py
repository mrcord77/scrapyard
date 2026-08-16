from fastapi.testclient import TestClient
from main import app

def main():
    c = TestClient(app)
    r = c.get("/health"); assert r.status_code == 200 and r.json()["ok"] is True
    cap = c.get("/capabilities"); assert cap.status_code == 200 and "template" in cap.json()
    print("Smoke check passed:", len(cap.json().get("routers_mounted", [])), "router(s) mounted")

if __name__ == "__main__":
    main()
