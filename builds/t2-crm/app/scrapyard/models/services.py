"""Generated services: CRUD + domain-rule enforcement."""
from __future__ import annotations
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import Lead


from scrapyard.api.domain_errors import WorkflowError, DomainRuleError


_MODELS = {'Lead': Lead}


class LeadService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Lead:
        obj = Lead(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Lead | None:
        return self.db.get(Lead, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Lead).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Lead | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

_SERVICES = {'Lead': LeadService}
