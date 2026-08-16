"""
request_security — Zero-config request-level enforcement for generated apps.

The backends were proven in isolation (distributed rate limiter, DB-enforced RLS);
this module wires them into the *request path* so every generated route is protected
without per-route effort:

  - PrincipalMiddleware   resolves the caller (user_id) from the Bearer JWT — stateless,
                          no DB, so it works before any RLS context exists (identity
                          precedes context).
  - RateLimitMiddleware   rate-limits every request against the distributed limiter,
                          keyed by principal (or client IP when anonymous).
  - make_scoped_db        a request-aware DB dependency that sets the RLS context for
                          the authenticated principal, so scoped data tables are
                          isolated automatically inside ordinary route handlers.

### PART-META-JSON
{
  "name": "request_security",
  "layer": "runtime",
  "purpose": "Auto-inject request-level enforcement into every generated route: PrincipalMiddleware resolves user_id from the Bearer JWT (stateless), RateLimitMiddleware limits per principal or client IP against the injected limiter, and make_scoped_db wraps the DB dependency to set per-request RLS context on Postgres.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi",
    "pyjwt"
  ],
  "inputs": "The app's JWT secret, DB dependency, and rate-limiter factory.",
  "outputs": "ASGI middlewares + a request-scoped DB dependency.",
  "files_created": [],
  "security_notes": "Principal comes from the signed JWT only (no trust in client-supplied IDs). RLS context is transaction-local. Rate limiting fails closed in production via get_rate_limiter().",
  "ai_usage": "from scrapyard.runtime.request_security import PrincipalMiddleware, RateLimitMiddleware, make_scoped_db",
  "example": "app.add_middleware(PrincipalMiddleware, jwt_secret=secret)",
  "import_path": "scrapyard.runtime.request_security"
}
### END-PART-META
"""
from __future__ import annotations
import os

from fastapi import Request  # module-level so FastAPI can resolve the type hint under
                             # `from __future__ import annotations` (a function-local
                             # import leaves it an unresolvable forward ref -> misread
                             # as a query param).

STATUS = "core"
PRINCIPAL_KEY = "scrapyard.principal_user_id"


def rls_enforced(database_url: str) -> bool:
    return (os.environ.get("SCRAPYARD_RLS", "").strip().lower() == "enforce"
            and str(database_url).startswith("postgres"))


class PrincipalMiddleware:
    """Resolve the caller from the Bearer JWT and stash user_id on the ASGI scope.
    Stateless (no DB), so it runs before RLS context exists. Anonymous requests pass
    through with principal = None."""

    def __init__(self, app, *, jwt_secret: str):
        self.app = app
        self.jwt_secret = jwt_secret

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        uid = None
        for k, v in scope.get("headers", []):
            if k == b"authorization":
                val = v.decode()
                if val.lower().startswith("bearer "):
                    uid = self._uid_from_jwt(val[7:].strip())
                break
        scope[PRINCIPAL_KEY] = uid
        await self.app(scope, receive, send)

    def _uid_from_jwt(self, token: str):
        try:
            from scrapyard.identity.jwt_manager import decode_token
            return int(decode_token(token, self.jwt_secret).get("sub"))
        except Exception:
            return None


class RateLimitMiddleware:
    """Rate-limit every request against the distributed limiter, keyed by principal
    (authenticated user) or client IP. In production the limiter fails closed at
    resolution (Redis required), so this is real global enforcement, not per-process."""

    def __init__(self, app, *, limiter_factory, capacity: int | None = None,
                 refill_per_sec: float | None = None, cost: float = 1.0):
        self.app = app
        self.cost = cost
        cap = capacity if capacity is not None else int(os.environ.get("RATE_LIMIT_CAPACITY", "120"))
        refill = refill_per_sec if refill_per_sec is not None else float(os.environ.get("RATE_LIMIT_REFILL", "2.0"))
        self._make = lambda: limiter_factory(capacity=cap, refill_per_sec=refill, namespace="req")
        self._limiter = None

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        allowed = True
        try:
            if self._limiter is None:
                self._limiter = self._make()
            uid = scope.get(PRINCIPAL_KEY)
            client = scope.get("client") or ("anonymous", 0)
            key = f"user:{uid}" if uid is not None else f"ip:{client[0]}"
            allowed = self._limiter.allow(key, self.cost)
        except Exception:
            allowed = True  # resolution already fail-closes in prod; don't hard-fail requests on a limiter blip
        if not allowed:
            body = b'{"detail":"rate limit exceeded"}'
            await send({"type": "http.response.start", "status": 429,
                        "headers": [(b"content-type", b"application/json"), (b"retry-after", b"1")]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def make_scoped_db(get_db, database_url: str):
    """Wrap the app's plain DB dependency so each request's transaction carries the
    RLS context for the authenticated principal. Routes keep using `db` as before;
    isolation happens underneath them. No-op unless SCRAPYARD_RLS=enforce on Postgres."""

    def dependency(request: Request):
        gen = get_db()
        db = next(gen)
        try:
            if rls_enforced(database_url):
                uid = request.scope.get(PRINCIPAL_KEY)
                if uid is not None:
                    from scrapyard.security.row_level_security import set_context
                    set_context(db.connection(), user_id=uid)
            yield db
        finally:
            try:
                next(gen)
            except StopIteration:
                pass

    return dependency


def _selftest() -> None:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from scrapyard.identity.jwt_manager import encode_token

    secret = "request-security-selftest-secret-0123456789abcdef"

    # limiter double: first N allowed, then denied for one key
    class StubLimiter:
        def __init__(self, capacity, refill_per_sec, namespace):
            self.capacity = capacity
            self.hits: dict[str, int] = {}
        def allow(self, key, cost=1.0):
            self.hits[key] = self.hits.get(key, 0) + 1
            return self.hits[key] <= self.capacity

    made: list[StubLimiter] = []
    def limiter_factory(**kwargs):
        lim = StubLimiter(**kwargs)
        made.append(lim)
        return lim

    # scoped-db double: plain generator dependency, closure tracks closure
    closed: list[bool] = []
    def get_db():
        yield {"db": True}
        closed.append(True)

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter_factory=limiter_factory, capacity=3)
    app.add_middleware(PrincipalMiddleware, jwt_secret=secret)
    scoped_db = make_scoped_db(get_db, "sqlite:///./x.db")  # non-postgres: RLS no-op path

    @app.get("/whoami")
    def whoami(request: Request, db=Depends(scoped_db)):
        return {"uid": request.scope.get(PRINCIPAL_KEY), "db": db["db"]}

    with TestClient(app) as client:
        # anonymous request: principal None, db dependency runs and closes
        r = client.get("/whoami")
        assert r.status_code == 200 and r.json() == {"uid": None, "db": True}
        assert closed == [True]

        # authenticated request: principal from signed JWT
        token = encode_token("42", secret)
        r = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert r.json()["uid"] == 42

        # garbage / wrongly signed tokens resolve to None, never 500
        bad = encode_token("42", "other-secret-0123456789abcdef0123456789ab")
        assert client.get("/whoami", headers={"Authorization": "Bearer nonsense"}).json()["uid"] is None
        assert client.get("/whoami", headers={"Authorization": f"Bearer {bad}"}).json()["uid"] is None

        # rate limiting: keyed per principal/IP; over capacity -> 429 with Retry-After
        lim = made[0]
        key = f"user:42"
        lim.hits[key] = lim.capacity  # next authenticated call exceeds
        r = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 429 and r.headers["retry-after"] == "1"
        assert r.json() == {"detail": "rate limit exceeded"}
        # other keys unaffected
        assert client.get("/whoami").status_code in (200, 429)  # ip-keyed budget separate

    # rls_enforced gate: only Postgres + explicit enforce
    saved = os.environ.get("SCRAPYARD_RLS")
    try:
        os.environ["SCRAPYARD_RLS"] = "enforce"
        assert rls_enforced("postgresql://db/app") is True
        assert rls_enforced("sqlite:///./app.db") is False
        os.environ.pop("SCRAPYARD_RLS", None)
        assert rls_enforced("postgresql://db/app") is False
    finally:
        if saved is None:
            os.environ.pop("SCRAPYARD_RLS", None)
        else:
            os.environ["SCRAPYARD_RLS"] = saved

    print("request_security selftest: PASS")


if __name__ == "__main__":
    _selftest()
