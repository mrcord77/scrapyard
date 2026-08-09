"""
media_library — Catalog uploaded media with metadata.

### PART-META-JSON
{
  "name": "media_library",
  "layer": "content",
  "purpose": "Catalog uploaded media with metadata.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: register_asset(db, key, content_type, size); list_assets(db); KeyAlreadyExistsError(...); AssetNotFoundError(...); InvalidMetadataError(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `register_asset` from `scrapyard.content.media_library` and call it as shown in `example`; run `py -m scrapyard.content.media_library` to see its offline selftest.",
  "example": "from scrapyard.content.media_library import register_asset",
  "import_path": "scrapyard.content.media_library"
}
### END-PART-META
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from typing import List, Dict, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from scrapyard.database.base_model import IntPKModel
from sqlalchemy import select

class KeyAlreadyExistsError(Exception):
    pass

class AssetNotFoundError(Exception):
    pass

class InvalidMetadataError(Exception):
    pass

class BulkOperationError(Exception):
    def __init__(self, errors: List[Dict[str, Any]]):
        self.errors = errors
        super().__init__("Bulk operation failed with the following errors: " + str(errors))

class MediaAsset(IntPKModel):
    __tablename__ = "media_assets"
    key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    content_type: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer, default=0)

def register_asset(db, key, content_type, size):
    a=MediaAsset(key=key, content_type=content_type, size=size); db.add(a); db.flush(); return a

def list_assets(db):
    return list(db.scalars(select(MediaAsset)))


def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from sqlalchemy import create_engine

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                a = register_asset(db, "img/logo.png", "image/png", 1234)
                assert a.id is not None and a.size == 1234
                register_asset(db, "docs/spec.pdf", "application/pdf", 999)
                db.commit()

                assets = list_assets(db)
                assert {x.key for x in assets} == {"img/logo.png", "docs/spec.pdf"}

                # unique key enforced at the DB level
                try:
                    register_asset(db, "img/logo.png", "image/png", 1)
                    db.commit()
                    raise AssertionError("duplicate key must fail")
                except IntegrityError:
                    db.rollback()
                assert len(list_assets(db)) == 2
        finally:
            engine.dispose()
    print("media_library self-test passed")


if __name__ == "__main__":
    _selftest()
