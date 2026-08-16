"""Generated services: CRUD + domain-rule enforcement."""
from __future__ import annotations
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import Well, Lease, ProductionLog, WorkOrder


from scrapyard.api.domain_errors import WorkflowError, DomainRuleError


_MODELS = {'Well': Well, 'Lease': Lease, 'ProductionLog': ProductionLog, 'WorkOrder': WorkOrder}


class WellService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Well:
        obj = Well(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Well | None:
        return self.db.get(Well, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Well).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Well | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class LeaseService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Lease:
        obj = Lease(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Lease | None:
        return self.db.get(Lease, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Lease).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Lease | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class ProductionLogService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> ProductionLog:
        obj = ProductionLog(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> ProductionLog | None:
        return self.db.get(ProductionLog, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(ProductionLog).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> ProductionLog | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class WorkOrderService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> WorkOrder:
        obj = WorkOrder(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> WorkOrder | None:
        return self.db.get(WorkOrder, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(WorkOrder).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> WorkOrder | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

_SERVICES = {'Well': WellService, 'Lease': LeaseService, 'ProductionLog': ProductionLogService, 'WorkOrder': WorkOrderService}
