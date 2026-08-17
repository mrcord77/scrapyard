"""Generated services: CRUD + domain-rule enforcement."""
from __future__ import annotations
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import Child, Meeting, Correspondence, ServiceEntry, ActionItem


from scrapyard.api.domain_errors import WorkflowError, DomainRuleError


_MODELS = {'Child': Child, 'Meeting': Meeting, 'Correspondence': Correspondence, 'ServiceEntry': ServiceEntry, 'ActionItem': ActionItem}


class ChildService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Child:
        obj = Child(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Child | None:
        return self.db.get(Child, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Child).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Child | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class MeetingService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Meeting:
        _v = data.get('child_id')
        if _v is not None:
            _ref = self.db.get(Child, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent child_id')
        obj = Meeting(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Meeting | None:
        return self.db.get(Meeting, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Meeting).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Meeting | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Meeting | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'requested': ['scheduled', 'refused'], 'scheduled': ['held', 'cancelled_by_school', 'rescheduled'], 'rescheduled': ['scheduled'], 'held': ['minutes_received', 'disputed'], 'minutes_received': [], 'disputed': ['resolved', 'state_complaint'], 'refused': ['state_complaint'], 'cancelled_by_school': ['rescheduled', 'state_complaint'], 'state_complaint': ['resolved'], 'resolved': []}
        _G = {}
        cur = getattr(obj, 'status')
        if to_state not in _T.get(cur, []):
            raise WorkflowError(f'illegal transition: {cur} -> {to_state}')
        for g in _G.get(to_state, []):
            if 'ref' in g:  # cross-entity guard: related row must be in an allowed status
                _rid = getattr(obj, g['ref'], None)
                _ro = self.db.get(_MODELS.get(g['entity']), _rid) if (_rid is not None and g.get('entity') in _MODELS) else None
                if _ro is None or getattr(_ro, g.get('field', 'status'), None) not in g.get('in', []):
                    raise WorkflowError(g.get('error') or 'related precondition failed')
            elif getattr(obj, g['field'], None) != g.get('equals'):
                raise WorkflowError(g.get('error') or f'guard failed entering {to_state}')
        setattr(obj, 'status', to_state)
        _E = {}
        for _eff in _E.get(to_state, []):
            if 'set_related' in _eff:  # mutate a related row (e.g. tool -> checked_out)
                _sr = _eff['set_related']; _rid = getattr(obj, _sr['ref'], None)
                if _sr.get('guarded') and _sr.get('entity') in _SERVICES:
                    # route through the related entity's own transition() so ITS
                    # transition table + guards apply (raises WorkflowError if blocked)
                    if _rid is not None:
                        _svc = _SERVICES[_sr['entity']](self.db)
                        if _svc.transition(_rid, _sr['value']) is None:
                            raise WorkflowError(f"{_sr['entity']} {_rid} not found for guarded effect")
                else:
                    _rel = self.db.get(_MODELS.get(_sr['entity']), _rid) if (_rid is not None and _sr.get('entity') in _MODELS) else None
                    if _rel is not None:
                        setattr(_rel, _sr.get('field', 'status'), _sr['value'])
            elif 'create' in _eff:  # auto-create a child record (e.g. incident, maintenance)
                _cr = _eff['create']; _vals = {}
                for _k, _v in (_cr.get('values') or {}).items():
                    _vals[_k] = getattr(obj, _v[1:], None) if (isinstance(_v, str) and _v.startswith('$')) else _v
                if _cr.get('entity') in _MODELS:
                    self.db.add(_MODELS[_cr['entity']](**_vals))
        self.db.flush(); return obj

class CorrespondenceService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Correspondence:
        obj = Correspondence(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Correspondence | None:
        return self.db.get(Correspondence, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Correspondence).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Correspondence | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class ServiceEntryService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> ServiceEntry:
        obj = ServiceEntry(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> ServiceEntry | None:
        return self.db.get(ServiceEntry, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(ServiceEntry).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> ServiceEntry | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class ActionItemService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> ActionItem:
        obj = ActionItem(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> ActionItem | None:
        return self.db.get(ActionItem, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(ActionItem).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> ActionItem | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> ActionItem | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'open': ['done', 'overdue', 'dropped'], 'overdue': ['done', 'escalated'], 'escalated': ['done'], 'done': [], 'dropped': []}
        _G = {}
        cur = getattr(obj, 'status')
        if to_state not in _T.get(cur, []):
            raise WorkflowError(f'illegal transition: {cur} -> {to_state}')
        for g in _G.get(to_state, []):
            if 'ref' in g:  # cross-entity guard: related row must be in an allowed status
                _rid = getattr(obj, g['ref'], None)
                _ro = self.db.get(_MODELS.get(g['entity']), _rid) if (_rid is not None and g.get('entity') in _MODELS) else None
                if _ro is None or getattr(_ro, g.get('field', 'status'), None) not in g.get('in', []):
                    raise WorkflowError(g.get('error') or 'related precondition failed')
            elif getattr(obj, g['field'], None) != g.get('equals'):
                raise WorkflowError(g.get('error') or f'guard failed entering {to_state}')
        setattr(obj, 'status', to_state)
        _E = {}
        for _eff in _E.get(to_state, []):
            if 'set_related' in _eff:  # mutate a related row (e.g. tool -> checked_out)
                _sr = _eff['set_related']; _rid = getattr(obj, _sr['ref'], None)
                if _sr.get('guarded') and _sr.get('entity') in _SERVICES:
                    # route through the related entity's own transition() so ITS
                    # transition table + guards apply (raises WorkflowError if blocked)
                    if _rid is not None:
                        _svc = _SERVICES[_sr['entity']](self.db)
                        if _svc.transition(_rid, _sr['value']) is None:
                            raise WorkflowError(f"{_sr['entity']} {_rid} not found for guarded effect")
                else:
                    _rel = self.db.get(_MODELS.get(_sr['entity']), _rid) if (_rid is not None and _sr.get('entity') in _MODELS) else None
                    if _rel is not None:
                        setattr(_rel, _sr.get('field', 'status'), _sr['value'])
            elif 'create' in _eff:  # auto-create a child record (e.g. incident, maintenance)
                _cr = _eff['create']; _vals = {}
                for _k, _v in (_cr.get('values') or {}).items():
                    _vals[_k] = getattr(obj, _v[1:], None) if (isinstance(_v, str) and _v.startswith('$')) else _v
                if _cr.get('entity') in _MODELS:
                    self.db.add(_MODELS[_cr['entity']](**_vals))
        self.db.flush(); return obj

_SERVICES = {'Child': ChildService, 'Meeting': MeetingService, 'Correspondence': CorrespondenceService, 'ServiceEntry': ServiceEntryService, 'ActionItem': ActionItemService}
