"""
auth_routes — Login/logout/refresh route handlers (login_routes).

### PART-META-JSON
{
  "name": "auth_routes",
  "layer": "identity",
  "purpose": "Login/logout/refresh route handlers (login_routes).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "fastapi",
    "pydantic[email]",
    "email-validator",
    "pyjwt"
  ],
  "inputs": "Public API: build_auth_router(get_db, *, jwt_secret); Creds(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `build_auth_router` from `scrapyard.identity.auth_routes` and call it as shown in `example`; run `py -m scrapyard.identity.auth_routes` to see its offline selftest.",
  "example": "from scrapyard.identity.auth_routes import build_auth_router",
  "import_path": "scrapyard.identity.auth_routes"
}
### END-PART-META
"""
from __future__ import annotations
from pydantic import BaseModel, EmailStr
STATUS = "core"


class Creds(BaseModel):
    # Module-scoped so FastAPI can resolve the body model under
    # `from __future__ import annotations` (a function-local model becomes an
    # unresolvable forward ref and FastAPI misreads it as a query param).
    email: EmailStr
    password: str


def build_auth_router(get_db, *, jwt_secret: str = "change-me"):
    """FastAPI router for register/login/logout/me wired to the real user +
    session + jwt parts. Pass your session dependency as `get_db`."""
    from fastapi import APIRouter, Depends, HTTPException, Header
    from scrapyard.identity.users import UserService
    from scrapyard.identity.session_manager import SessionManager
    from scrapyard.identity.jwt_manager import issue_pair, decode_token

    router = APIRouter(prefix="/auth", tags=["auth"])

    def _bearer_token(authorization: str | None = Header(default=None)) -> str:
        # The credential travels in the Authorization header, never the URL/query
        # (query strings leak into access logs, referrers, and browser history).
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "missing or malformed Authorization header")
        return authorization[7:].strip()

    def _resolve_uid(token: str, db):
        # Accept either credential login returns: the opaque session token
        # (revocable, looked up server-side) or the stateless JWT access token.
        uid = SessionManager(db).user_id_for(token)
        if uid:
            return uid
        try:
            claims = decode_token(token, jwt_secret)
            return int(claims.get("sub"))
        except Exception:
            return None

    @router.post("/register")
    def register(body: Creds, db=Depends(get_db)):
        svc = UserService(db)
        if svc.get_by_email(body.email):
            raise HTTPException(409, "email already registered")
        try:
            u = svc.create(body.email, body.password); db.commit()
        except Exception as e:
            # surface password-policy / validation failures as a clean 422,
            # not an unhandled 500 (a frontend shows the message to the user).
            from scrapyard.security.password_policy import PolicyError
            if isinstance(e, PolicyError):
                raise HTTPException(422, str(e))
            raise
        return {"id": u.id, "email": u.email}

    @router.post("/login")
    def login(body: Creds, db=Depends(get_db)):
        u = UserService(db).authenticate(body.email, body.password)
        if not u:
            raise HTTPException(401, "invalid credentials")
        session_token = SessionManager(db).create(u.id); db.commit()
        tokens = issue_pair(str(u.id), jwt_secret)
        return {"session": session_token, **tokens}

    @router.post("/logout")
    def logout(token: str = Depends(_bearer_token), db=Depends(get_db)):
        ok = SessionManager(db).revoke(token); db.commit()
        return {"revoked": ok}

    @router.get("/me")
    def me(token: str = Depends(_bearer_token), db=Depends(get_db)):
        uid = _resolve_uid(token, db)
        if not uid:
            raise HTTPException(401, "invalid or expired credentials")
        u = UserService(db).get(uid)
        if not u:
            raise HTTPException(401, "invalid or expired credentials")
        return {"id": u.id, "email": u.email, "verified": u.is_verified}

    return router


def _selftest() -> None:
    """Offline self-test: drive the real router end-to-end over in-memory SQLite."""
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except Exception as e:  # noqa: BLE001
        print(f"auth_routes self-test SKIPPED (fastapi/testclient unavailable: {e})")
        return

    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import Base
    import scrapyard.identity.users  # noqa: F401  (register User table)
    import scrapyard.identity.session_manager  # noqa: F401  (register Session table)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def get_db():
        db = Session(engine)
        try:
            yield db
        finally:
            db.close()

    try:
        app = FastAPI()
        app.include_router(build_auth_router(get_db, jwt_secret="test-secret"))
        client = TestClient(app)

        # register
        r = client.post("/auth/register",
                        json={"email": "a@example.com", "password": "Sup3rSecret!"})
        assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"

        # login returns a session token + jwt pair
        r = client.post("/auth/login",
                        json={"email": "a@example.com", "password": "Sup3rSecret!"})
        assert r.status_code == 200, f"login failed: {r.text}"
        session_token = r.json()["session"]

        # /me with the valid session token resolves the user
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {session_token}"})
        assert r.status_code == 200 and r.json()["email"] == "a@example.com"

        # negative: wrong password is rejected
        r = client.post("/auth/login",
                        json={"email": "a@example.com", "password": "wrong-pass!"})
        assert r.status_code == 401, "wrong credentials must be 401"

        # negative: a garbage bearer token is rejected
        r = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
        assert r.status_code == 401, "invalid token must be 401"
    finally:
        engine.dispose()
    print("auth_routes self-test passed")


if __name__ == "__main__":
    _selftest()
