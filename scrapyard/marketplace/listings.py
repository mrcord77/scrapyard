"""
listings — Marketplace listings: model, service, and routes (list/detail/create).

### PART-META-JSON
{
  "name": "listings",
  "layer": "marketplace",
  "purpose": "Marketplace listings: DB-backed list/detail (public) and seller-key-gated create.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi",
    "sqlalchemy"
  ],
  "inputs": "build_marketplace_router(get_db): GET /marketplace/listings, GET /marketplace/listings/{id}, POST /marketplace/listings (X-Seller-Key gated).",
  "outputs": "Active listings (paginated, optional title filter); listing detail; created listing.",
  "files_created": [],
  "security_notes": "Reads expose only ACTIVE listings (drafts/removed are never listed or served). Creation is NOT an open public write: it requires X-Seller-Key to equal env MARKETPLACE_SELLER_KEY and returns 503 if that key is unset, so a generated marketplace never ships an ungated write. price_cents is validated non-negative. For a real multi-seller marketplace, replace the shared seller key with per-user auth (the template includes users) + moderation before listings go active; gate behind rate_limiting.",
  "ai_usage": "router = build_marketplace_router(get_db); mount it. Set MARKETPLACE_SELLER_KEY to enable listing creation. Listings default to active; wire admin/moderation_tools to require review before publish.",
  "example": "from scrapyard.marketplace.listings import build_marketplace_router; app.include_router(build_marketplace_router(get_db))",
  "import_path": "scrapyard.marketplace.listings"
}
### END-PART-META
"""
from __future__ import annotations
import os
from datetime import datetime

STATUS = "core"

from sqlalchemy import String, Text, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import IntPKModel

ACTIVE, REMOVED = "active", "removed"


class Listing(IntPKModel):
    __tablename__ = "marketplace_listings"
    title: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    seller_email: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default=ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ListingService:
    def __init__(self, db):
        self.db = db

    def create(self, title, description, price_cents, seller_email):
        row = Listing(title=title, description=description,
                      price_cents=price_cents, seller_email=seller_email, status=ACTIVE)
        self.db.add(row); self.db.flush()
        return row

    def active(self, q=None, limit=50, offset=0):
        from sqlalchemy import select
        stmt = select(Listing).where(Listing.status == ACTIVE)
        if q:
            stmt = stmt.where(Listing.title.ilike(f"%{q}%"))
        stmt = stmt.order_by(Listing.id.desc()).limit(min(limit, 200)).offset(max(offset, 0))
        return list(self.db.scalars(stmt))

    def by_id(self, listing_id):
        row = self.db.get(Listing, listing_id)
        return row if row and row.status == ACTIVE else None


def _new_listing_model():
    from pydantic import BaseModel, Field

    class NewListing(BaseModel):
        title: str
        description: str = ""
        price_cents: int = Field(default=0, ge=0)
        seller_email: str = ""
    return NewListing


NewListing = _new_listing_model()  # module scope so FastAPI resolves the body annotation


def build_marketplace_router(get_db):
    from fastapi import APIRouter, Depends, HTTPException, Header

    router = APIRouter(prefix="/marketplace", tags=["marketplace"])

    def _view(l: Listing) -> dict:
        return {"id": l.id, "title": l.title, "description": l.description,
                "price_cents": l.price_cents, "seller_email": l.seller_email,
                "created_at": l.created_at.isoformat() if l.created_at else None}

    @router.get("/listings")
    def list_listings(q: str | None = None, limit: int = 50, offset: int = 0, db=Depends(get_db)):
        return [_view(l) for l in ListingService(db).active(q=q, limit=limit, offset=offset)]

    @router.get("/listings/{listing_id}")
    def get_listing(listing_id: int, db=Depends(get_db)):
        row = ListingService(db).by_id(listing_id)
        if not row:
            raise HTTPException(404, "listing not found")
        return _view(row)

    @router.post("/listings", status_code=201)
    def create_listing(body: NewListing, x_seller_key: str | None = Header(default=None),
                       db=Depends(get_db)):
        configured = os.environ.get("MARKETPLACE_SELLER_KEY")
        if not configured:
            raise HTTPException(503, "listing creation disabled — set MARKETPLACE_SELLER_KEY to enable")
        if x_seller_key != configured:
            raise HTTPException(401, "invalid seller key")
        row = ListingService(db).create(body.title, body.description, body.price_cents, body.seller_email)
        db.commit()
        return _view(row)

    return router


def _selftest() -> None:
    """Offline self-test: service CRUD + key-gated router."""
    import tempfile
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                svc = ListingService(db)
                row = svc.create("Vintage Lathe", "3-phase", 250000, "seller@example.com")
                db.commit()
                assert svc.by_id(row.id).title == "Vintage Lathe"
                assert [l.id for l in svc.active(q="lathe")] == [row.id]
                assert svc.active(q="nomatch") == []
                row.status = REMOVED
                db.commit()
                assert svc.by_id(row.id) is None
                assert svc.active() == []
                row.status = ACTIVE
                db.commit()

            def get_db():
                db = Session(engine)
                try:
                    yield db
                finally:
                    db.close()

            app = FastAPI()
            app.include_router(build_marketplace_router(get_db))
            client = TestClient(app)

            r = client.get("/marketplace/listings")
            assert r.status_code == 200 and len(r.json()) == 1
            lid = r.json()[0]["id"]
            assert client.get(f"/marketplace/listings/{lid}").status_code == 200
            assert client.get("/marketplace/listings/99999").status_code == 404

            old_key = os.environ.pop("MARKETPLACE_SELLER_KEY", None)
            try:
                body = {"title": "New Part", "price_cents": 100}
                assert client.post("/marketplace/listings", json=body).status_code == 503
                os.environ["MARKETPLACE_SELLER_KEY"] = "sk"
                r = client.post("/marketplace/listings", json=body,
                                headers={"x-seller-key": "bad"})
                assert r.status_code == 401
                r = client.post("/marketplace/listings", json=body,
                                headers={"x-seller-key": "sk"})
                assert r.status_code == 201 and r.json()["title"] == "New Part"
                # Negative price rejected by the pydantic model
                r = client.post("/marketplace/listings",
                                json={"title": "Bad", "price_cents": -5},
                                headers={"x-seller-key": "sk"})
                assert r.status_code == 422
            finally:
                if old_key is None:
                    os.environ.pop("MARKETPLACE_SELLER_KEY", None)
                else:
                    os.environ["MARKETPLACE_SELLER_KEY"] = old_key
        finally:
            engine.dispose()
    print("listings self-test passed")


if __name__ == "__main__":
    _selftest()
