"""
timestamps — created_at/updated_at mixin with auto-touch.

### PART-META-JSON
{
  "name": "timestamps",
  "layer": "database",
  "purpose": "created_at/updated_at mixin with auto-touch.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: add_timestamps(model_class, timezone); touch_on_update(exclude); auto_archive(model_class, on_delete); filter_by_timestamps(query, field, start, end); paginate_timestamps(query, page, page_size, order_by); TimestampMixin(...) (plus more).",
  "outputs": "Returns: add_timestamps -> Type; auto_archive -> Type; filter_by_timestamps -> Query; paginate_timestamps -> Dict[str, Any]; audit_on_change -> Type.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `add_timestamps` from `scrapyard.database.timestamps` and call it as shown in `example`; run `py -m scrapyard.database.timestamps` to see its offline selftest.",
  "example": "from scrapyard.database.timestamps import add_timestamps",
  "import_path": "scrapyard.database.timestamps"
}
### END-PART-META
"""
from __future__ import annotations
from datetime import datetime

STATUS = "core"

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds created_at / updated_at, auto-managed by the database."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


from typing import Any, Dict, List, Optional, Type, Union
from sqlalchemy import String
from sqlalchemy.orm import Session, Query
from sqlalchemy.ext.declarative import declared_attr
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_


def add_timestamps(model_class: Type, timezone: bool = True) -> Type:
    """Configurable mixin factory to apply `created_at`/`updated_at` fields to models."""
    class TimestampedModel(model_class):
        @declared_attr
        def __tablename__(cls) -> str:
            return f"{model_class.__name__.lower()}_{timezone}"

        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=timezone), server_default=func.now(), nullable=False)
        updated_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=timezone), server_default=func.now(), onupdate=func.now(), nullable=False)

    return TimestampedModel


def touch_on_update(exclude: Optional[List[str]] = None):
    """Decorator to manually trigger `updated_at` update on model save."""
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            if exclude:
                for field in exclude:
                    if hasattr(self, field):
                        delattr(self, field)
            self.updated_at = datetime.now()
            return func(self, *args, **kwargs)
        return wrapper
    return decorator


def auto_archive(model_class: Type, on_delete: str = "soft") -> Type:
    """Configurable soft-delete behavior with `archived_at` field."""
    class ArchivedModel(model_class):
        archived_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), nullable=True)

        @declared_attr
        def __mapper_args__(cls) -> Dict[str, Any]:
            if on_delete == "soft":
                return {"polymorphic_on": cls.archived_at}
            elif on_delete == "hard":
                return {"polymorphic_identity": True}
            else:
                raise ValueError("Invalid on_delete value")

        @classmethod
        def soft_delete(cls, session: Session, instance_id: int):
            """Soft delete an instance."""
            instance = session.query(cls).filter_by(id=instance_id).first()
            if not instance:
                raise HTTPException(status_code=404, detail="Instance not found")
            instance.archived_at = datetime.now()

        @classmethod
        def hard_delete(cls, session: Session, instance_id: int):
            """Hard delete an instance."""
            instance = session.query(cls).filter_by(id=instance_id).first()
            if not instance:
                raise HTTPException(status_code=404, detail="Instance not found")
            session.delete(instance)

    return ArchivedModel


def filter_by_timestamps(query: Query, field: str, start: datetime, end: datetime) -> Query:
    """Filter by time ranges on `created_at` or `updated_at`, with optional `tz-aware` support."""
    if field not in ["created_at", "updated_at"]:
        raise ValueError("Invalid field. Must be 'created_at' or 'updated_at'")
    return query.filter(and_(getattr(query._mapper_zero(), field) >= start, getattr(query._mapper_zero(), field) <= end))


def paginate_timestamps(query: Query, page: int = 1, page_size: int = 20, order_by: str = "created_at") -> Dict[str, Any]:
    """Pagination helper for timestamp-based queries."""
    if order_by not in ["created_at", "updated_at"]:
        raise ValueError("Invalid order_by. Must be 'created_at' or 'updated_at'")
    offset = (page - 1) * page_size
    results = query.order_by(getattr(query._mapper_zero(), order_by)).offset(offset).limit(page_size).all()
    total_count = query.count()
    return {"items": results, "total_count": total_count}


def audit_on_change(model_class: Type, audit_level: str = "change") -> Type:
    """Hook to log changes to `created_at`/`updated_at` fields."""
    class AuditedModel(model_class):
        @declared_attr
        def __tablename__(cls) -> str:
            return f"{model_class.__name__.lower()}_audit"

        audit_level: Mapped[str] = mapped_column(String, default="change")

        @classmethod
        def log_change(cls, session: Session, instance_id: int):
            """Log a change."""
            instance = session.query(model_class).filter_by(id=instance_id).first()
            if not instance:
                raise HTTPException(status_code=404, detail="Instance not found")
            audit_entry = cls(instance_id=instance_id)
            session.add(audit_entry)

    return AuditedModel


def serialize_timestamps(obj: Any, format: str = "iso") -> Dict[str, str]:
    """Helper to format `created_at`/`updated_at` fields for JSON output."""
    if not isinstance(obj, (dict, BaseModel)):
        raise ValueError("Invalid object type")
    serialized = {}
    for field in ["created_at", "updated_at"]:
        value = getattr(obj, field, None)
        if value:
            serialized[field] = value.strftime(format) if format else str(value)
    return serialized


def bulk_update_timestamps(session: Session, model_class: Type, filter: Optional[Dict[str, Any]] = None, exclude: Optional[List[str]] = None):
    """Bulk update helper to apply `updated_at` to multiple records."""
    query = session.query(model_class)
    if filter:
        query = query.filter_by(**filter)
    for instance in query.all():
        if exclude and any(getattr(instance, field) is not None for field in exclude):
            continue
        instance.updated_at = datetime.now()
    session.commit()


def _selftest() -> None:
    import time
    from sqlalchemy import create_engine, String
    from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
    from scrapyard.database.base_model import Base, IntPKModel

    class Row(TimestampMixin, IntPKModel):
        __tablename__ = "timestamps_selftest_row"
        val: Mapped[str] = mapped_column(String(20))

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    r = Row(val="one")
    db.add(r); db.commit(); db.refresh(r)
    assert r.created_at is not None and r.updated_at is not None   # server defaults populate
    created = r.created_at

    time.sleep(1.1)                                       # cross SQLite's 1s CURRENT_TIMESTAMP tick
    r.val = "two"; db.commit(); db.refresh(r)
    assert r.updated_at > created                         # updated_at advances on update
    assert r.created_at == created                        # negative: created_at must NOT move
    db.close()
    print("timestamps selftest: PASS")


if __name__ == "__main__":
    _selftest()
