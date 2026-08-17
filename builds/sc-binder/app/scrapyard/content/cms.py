"""
cms — Generic content model + publish workflow.

### PART-META-JSON
{
  "name": "cms",
  "layer": "content",
  "purpose": "Generic content model + publish workflow.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: upsert(db, key, value); get(db, key, default); create(db, key, value); get_block(db, key); update(db, key, value); DuplicateKeyError(...); NotFoundError(...); WorkflowError(...) (plus more).",
  "outputs": "Returns: create -> ContentBlock; get_block -> ContentBlock; update -> ContentBlock; delete -> bool; list_all -> Sequence[ContentBlock].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `upsert` from `scrapyard.content.cms` and call it as shown in `example`; run `py -m scrapyard.content.cms` to see its offline selftest.",
  "example": "from scrapyard.content.cms import upsert",
  "import_path": "scrapyard.content.cms"
}
### END-PART-META
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

STATUS = "core"

log = logging.getLogger("scrapyard.content.cms")

# publish workflow states for a block
DRAFT, PUBLISHED, ARCHIVED = "draft", "published", "archived"
_WORKFLOW = {DRAFT: {PUBLISHED, ARCHIVED}, PUBLISHED: {ARCHIVED}, ARCHIVED: {DRAFT}}


class DuplicateKeyError(Exception):
    pass


class NotFoundError(Exception):
    pass


class WorkflowError(Exception):
    pass


class ContentBlock(IntPKModel):
    __tablename__ = "cms_blocks"
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(20), default=DRAFT)


# -- original core API ----------------------------------------------------------
def upsert(db, key, value):
    b = db.scalars(select(ContentBlock).where(ContentBlock.key == key)).first()
    if b:
        b.value = value
    else:
        b = ContentBlock(key=key, value=value)
        db.add(b)
    db.flush()
    return b


def get(db, key, default=""):
    b = db.scalars(select(ContentBlock).where(ContentBlock.key == key)).first()
    return b.value if b else default


# -- extended service API --------------------------------------------------------
def create(db: Session, key: str, value: str) -> ContentBlock:
    """Strict create: raises DuplicateKeyError if the key exists (use upsert()
    for create-or-replace semantics)."""
    if db.scalars(select(ContentBlock).where(ContentBlock.key == key)).first():
        raise DuplicateKeyError(f"content key {key!r} already exists")
    b = ContentBlock(key=key, value=value)
    db.add(b)
    db.flush()
    return b


def get_block(db: Session, key: str) -> ContentBlock:
    b = db.scalars(select(ContentBlock).where(ContentBlock.key == key)).first()
    if b is None:
        raise NotFoundError(f"content key {key!r} not found")
    return b


def update(db: Session, key: str, value: str) -> ContentBlock:
    b = get_block(db, key)
    b.value = value
    db.flush()
    return b


def delete(db: Session, key: str) -> bool:
    b = get_block(db, key)
    db.delete(b)
    db.flush()
    return True


def list_all(db: Session, page: int = 1, per_page: int = 20,
             state: Optional[str] = None) -> Sequence[ContentBlock]:
    stmt = select(ContentBlock).order_by(ContentBlock.key)
    if state is not None:
        stmt = stmt.where(ContentBlock.state == state)
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    return list(db.scalars(stmt))


def search(db: Session, query: str, page: int = 1,
           per_page: int = 20) -> Sequence[ContentBlock]:
    like = f"%{query}%"
    stmt = (select(ContentBlock)
            .where(ContentBlock.key.like(like) | ContentBlock.value.like(like))
            .order_by(ContentBlock.key)
            .offset((page - 1) * per_page).limit(per_page))
    return list(db.scalars(stmt))


def bulk_upsert(db: Session, items: List[Dict[str, Any]]) -> List[ContentBlock]:
    """Upsert many {key, value} dicts; portable (no dialect-specific SQL)."""
    out = [upsert(db, item["key"], item["value"]) for item in items]
    db.flush()
    return out


# -- publish workflow ------------------------------------------------------------
def transition(db: Session, key: str, to_state: str) -> ContentBlock:
    """Move a block through draft -> published -> archived (archived may return
    to draft). Illegal moves raise WorkflowError."""
    b = get_block(db, key)
    allowed = _WORKFLOW.get(b.state, set())
    if to_state not in allowed:
        raise WorkflowError(f"cannot move {key!r} from {b.state!r} to {to_state!r}")
    b.state = to_state
    db.flush()
    log.info("cms %s: %s", key, to_state)
    return b


def publish(db: Session, key: str) -> ContentBlock:
    return transition(db, key, PUBLISHED)


def archive(db: Session, key: str) -> ContentBlock:
    return transition(db, key, ARCHIVED)


def published_blocks(db: Session) -> Sequence[ContentBlock]:
    return list(db.scalars(
        select(ContentBlock).where(ContentBlock.state == PUBLISHED)
        .order_by(ContentBlock.key)))


def serialize(block: ContentBlock) -> Dict[str, Any]:
    return {"id": block.id, "key": block.key, "value": block.value,
            "state": block.state}


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
                # upsert + get
                upsert(db, "home.title", "Welcome")
                assert get(db, "home.title") == "Welcome"
                upsert(db, "home.title", "Welcome v2")
                assert get(db, "home.title") == "Welcome v2"
                assert get(db, "missing", "fallback") == "fallback"

                # strict create + duplicate
                create(db, "footer.text", "(c) 2026")
                try:
                    create(db, "footer.text", "again")
                    raise AssertionError("duplicate key must raise")
                except DuplicateKeyError:
                    pass

                # update / delete / not found
                update(db, "footer.text", "(c) 2027")
                assert get_block(db, "footer.text").value == "(c) 2027"
                try:
                    get_block(db, "ghost")
                    raise AssertionError("missing key must raise")
                except NotFoundError:
                    pass
                assert delete(db, "footer.text") is True

                # workflow draft -> published -> archived -> draft
                create(db, "promo", "Sale!")
                assert get_block(db, "promo").state == DRAFT
                publish(db, "promo")
                assert get_block(db, "promo").state == PUBLISHED
                assert [b.key for b in published_blocks(db)] == ["promo"]
                try:
                    transition(db, "promo", PUBLISHED)
                    raise AssertionError("illegal transition must raise")
                except WorkflowError:
                    pass
                archive(db, "promo")
                transition(db, "promo", DRAFT)
                assert get_block(db, "promo").state == DRAFT

                # search / list / bulk
                bulk_upsert(db, [{"key": "a.one", "value": "alpha"},
                                 {"key": "a.two", "value": "beta"}])
                assert [b.key for b in search(db, "alpha")] == ["a.one"]
                assert len(list_all(db)) >= 3
                s = serialize(get_block(db, "a.one"))
                assert s["key"] == "a.one" and s["state"] == DRAFT
        finally:
            engine.dispose()
    print("cms self-test passed")


if __name__ == "__main__":
    _selftest()
