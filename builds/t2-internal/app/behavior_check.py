from fastapi.testclient import TestClient
from main import app


def main():
    c = TestClient(app)
    required = ['/admin/status']
    missing, broken, served, gated = [], [], 0, 0
    for p in required:
        resp = c.get(p)
        sc = resp.status_code
        if sc == 404:
            missing.append(p)            # route not mounted
        elif sc >= 500:
            broken.append((p, sc))       # route mounted but erroring
        elif sc in (401, 403):
            gated += 1                   # mounted and correctly requiring auth
        elif sc < 400:
            served += 1                  # mounted and actually serving
    assert not missing, ("required feature routes missing/unmounted: " + ", ".join(missing))
    assert not broken, ("feature routes returned a server error (5xx): " + str(broken))
    # a route that exists must DO something: either serve a success or correctly gate on auth.
    assert served >= 1 or gated == len(required), \
        ("no feature route served a success and not all are auth-gated", served, gated, len(required))
    print(f"behavior_check passed: {len(required)} routes mounted, none 5xx, "
          f"{served} served 2xx/3xx, {gated} correctly auth-gated")


if __name__ == "__main__":
    main()
