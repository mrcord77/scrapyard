"""
content_routes — Public content API over the DB-backed blog/CMS parts.

### PART-META-JSON
{
  "name": "content_routes",
  "layer": "content",
  "purpose": "DB-backed content endpoints: list/read published content, with key-gated authoring.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi",
    "sqlalchemy"
  ],
  "inputs": "build_content_router(get_db): GET /content, GET /content/{slug}, POST /content (X-Admin-Key gated).",
  "outputs": "Published posts (list/detail with rendered HTML); authoring creates a post when authorized.",
  "files_created": [],
  "security_notes": "Reads are public (published content only — drafts are never listed or served). Authoring (POST /content) is NOT open: it requires the X-Admin-Key header to equal env CONTENT_ADMIN_KEY, and returns 503 if that key is unset, so a generated content_site never ships an ungated public write endpoint. Body is rendered from markdown; if you later accept untrusted HTML, sanitize it. Gate authoring behind real RBAC before production if you wire an auth stack.",
  "ai_usage": "router = build_content_router(get_db); mount it. Set CONTENT_ADMIN_KEY to enable authoring. Backed by scrapyard.content.blog (Post/BlogService) + markdown_pages.render_markdown.",
  "example": "from scrapyard.content.content_routes import build_content_router; app.include_router(build_content_router(get_db))",
  "import_path": "scrapyard.content.content_routes"
}
### END-PART-META
"""
from __future__ import annotations
import os

STATUS = "core"


def _new_post_model():
    from pydantic import BaseModel

    class NewPost(BaseModel):
        title: str
        body: str
        published: bool = True
    return NewPost


NewPost = _new_post_model()  # module-scope so FastAPI resolves the body annotation


def build_content_router(get_db):
    from fastapi import APIRouter, Depends, HTTPException, Header
    from scrapyard.content.blog import BlogService
    from scrapyard.content.markdown_pages import render_markdown

    router = APIRouter(prefix="/content", tags=["content"])

    @router.get("")
    def list_content(db=Depends(get_db)):
        """Published content only (drafts never leak)."""
        posts = BlogService(db).published()
        return [{"slug": p.slug, "title": p.title,
                 "created_at": p.created_at.isoformat() if p.created_at else None}
                for p in posts]

    @router.get("/{slug}")
    def get_content(slug: str, db=Depends(get_db)):
        post = BlogService(db).by_slug(slug)
        if not post or not post.published:
            raise HTTPException(404, "content not found")
        return {"slug": post.slug, "title": post.title,
                "body_html": render_markdown(post.body), "published": post.published}

    @router.post("", status_code=201)
    def create_content(body: NewPost, x_admin_key: str | None = Header(default=None),
                       db=Depends(get_db)):
        """Authoring is key-gated — never an open public write."""
        configured = os.environ.get("CONTENT_ADMIN_KEY")
        if not configured:
            raise HTTPException(503, "authoring disabled — set CONTENT_ADMIN_KEY to enable")
        if x_admin_key != configured:
            raise HTTPException(401, "invalid admin key")
        post = BlogService(db).create(body.title, body.body, published=body.published)
        db.commit()
        return {"slug": post.slug, "title": post.title}

    return router


def _selftest() -> None:
    """Offline self-test: mount the router and exercise the endpoints."""
    import os as _os
    import tempfile
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from scrapyard.database.base_model import IntPKModel
    import scrapyard.content.blog  # noqa: F401 - register blog tables

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{_os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            def get_db():
                db = Session(engine)
                try:
                    yield db
                finally:
                    db.close()

            app = FastAPI()
            app.include_router(build_content_router(get_db))
            client = TestClient(app)

            old_key = _os.environ.pop("CONTENT_ADMIN_KEY", None)
            try:
                # Authoring disabled without the key configured
                r = client.post("/content", json={"title": "T", "body": "B"})
                assert r.status_code == 503

                _os.environ["CONTENT_ADMIN_KEY"] = "k3y"
                r = client.post("/content", json={"title": "T", "body": "B"},
                                headers={"x-admin-key": "wrong"})
                assert r.status_code == 401

                r = client.post("/content", json={"title": "My Post", "body": "**bold** text"},
                                headers={"x-admin-key": "k3y"})
                assert r.status_code == 201 and r.json()["slug"] == "my-post"

                # Draft creation never leaks in the list
                client.post("/content", json={"title": "Draft", "body": "x", "published": False},
                            headers={"x-admin-key": "k3y"})

                r = client.get("/content")
                assert r.status_code == 200
                assert [p["slug"] for p in r.json()] == ["my-post"]

                r = client.get("/content/my-post")
                assert r.status_code == 200
                assert "<strong>bold</strong>" in r.json()["body_html"]
                assert client.get("/content/draft").status_code == 404
                assert client.get("/content/ghost").status_code == 404
            finally:
                if old_key is None:
                    _os.environ.pop("CONTENT_ADMIN_KEY", None)
                else:
                    _os.environ["CONTENT_ADMIN_KEY"] = old_key
        finally:
            engine.dispose()
    print("content_routes self-test passed")


if __name__ == "__main__":
    _selftest()
