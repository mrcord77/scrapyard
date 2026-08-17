"""Generated services: CRUD + domain-rule enforcement."""
from __future__ import annotations
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import CareRecipient, CareTask, Medication, DoseLog, Appointment, Update


from scrapyard.api.domain_errors import WorkflowError, DomainRuleError


_MODELS = {'CareRecipient': CareRecipient, 'CareTask': CareTask, 'Medication': Medication, 'DoseLog': DoseLog, 'Appointment': Appointment, 'Update': Update}


class CareRecipientService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> CareRecipient:
        obj = CareRecipient(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> CareRecipient | None:
        return self.db.get(CareRecipient, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(CareRecipient).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> CareRecipient | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class CareTaskService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> CareTask:
        _v = data.get('recipient_id')
        if _v is not None:
            _ref = self.db.get(CareRecipient, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent recipient_id')
        obj = CareTask(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> CareTask | None:
        return self.db.get(CareTask, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(CareTask).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> CareTask | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> CareTask | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'open': ['claimed', 'dropped'], 'claimed': ['done', 'open', 'missed'], 'missed': ['open', 'escalated'], 'escalated': ['done'], 'done': [], 'dropped': []}
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

class MedicationService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Medication:
        obj = Medication(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Medication | None:
        return self.db.get(Medication, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Medication).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Medication | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Medication | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'active': ['paused', 'discontinued'], 'paused': ['active', 'discontinued'], 'discontinued': []}
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

class DoseLogService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> DoseLog:
        _v = data.get('medication_id')
        if _v is not None:
            _ref = self.db.get(Medication, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent medication_id')
            if getattr(_ref, 'status', None) not in ['active', 'paused']:
                raise DomainRuleError('dose logs attach to a current medication')
        obj = DoseLog(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> DoseLog | None:
        return self.db.get(DoseLog, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(DoseLog).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> DoseLog | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class AppointmentService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Appointment:
        obj = Appointment(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Appointment | None:
        return self.db.get(Appointment, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Appointment).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Appointment | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Appointment | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'scheduled': ['attended', 'missed', 'cancelled'], 'missed': ['scheduled'], 'attended': [], 'cancelled': ['scheduled']}
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

class UpdateService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Update:
        obj = Update(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Update | None:
        return self.db.get(Update, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Update).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Update | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

_SERVICES = {'CareRecipient': CareRecipientService, 'CareTask': CareTaskService, 'Medication': MedicationService, 'DoseLog': DoseLogService, 'Appointment': AppointmentService, 'Update': UpdateService}
