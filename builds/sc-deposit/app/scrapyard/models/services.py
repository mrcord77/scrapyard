"""Generated services: CRUD + domain-rule enforcement."""
from __future__ import annotations
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import Tenancy, EvidenceShot, Deduction, DisputeLetter


from scrapyard.api.domain_errors import WorkflowError, DomainRuleError


_MODELS = {'Tenancy': Tenancy, 'EvidenceShot': EvidenceShot, 'Deduction': Deduction, 'DisputeLetter': DisputeLetter}


class TenancyService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Tenancy:
        obj = Tenancy(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Tenancy | None:
        return self.db.get(Tenancy, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Tenancy).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Tenancy | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Tenancy | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'active': ['notice_given'], 'notice_given': ['moved_out'], 'moved_out': ['deposit_returned', 'deductions_received'], 'deductions_received': ['disputing', 'accepted'], 'disputing': ['resolved_full', 'resolved_partial', 'small_claims'], 'small_claims': ['resolved_full', 'resolved_partial', 'lost'], 'deposit_returned': [], 'accepted': [], 'resolved_full': [], 'resolved_partial': [], 'lost': []}
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

class EvidenceShotService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> EvidenceShot:
        _v = data.get('tenancy_id')
        if _v is not None:
            _ref = self.db.get(Tenancy, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent tenancy_id')
            if getattr(_ref, 'status', None) not in ['active', 'notice_given', 'moved_out', 'deductions_received', 'disputing']:
                raise DomainRuleError('evidence attaches to a live tenancy')
        obj = EvidenceShot(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> EvidenceShot | None:
        return self.db.get(EvidenceShot, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(EvidenceShot).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> EvidenceShot | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class DeductionService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Deduction:
        obj = Deduction(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Deduction | None:
        return self.db.get(Deduction, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Deduction).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Deduction | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Deduction | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'contested': ['dropped', 'upheld', 'accepted'], 'dropped': [], 'upheld': [], 'accepted': []}
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

class DisputeLetterService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> DisputeLetter:
        obj = DisputeLetter(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> DisputeLetter | None:
        return self.db.get(DisputeLetter, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(DisputeLetter).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> DisputeLetter | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

_SERVICES = {'Tenancy': TenancyService, 'EvidenceShot': EvidenceShotService, 'Deduction': DeductionService, 'DisputeLetter': DisputeLetterService}
