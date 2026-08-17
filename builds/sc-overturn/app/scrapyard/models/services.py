"""Generated services: CRUD + domain-rule enforcement."""
from __future__ import annotations
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import Claim, Denial, Appeal, EvidenceItem, CallLog


from scrapyard.api.domain_errors import WorkflowError, DomainRuleError


_MODELS = {'Claim': Claim, 'Denial': Denial, 'Appeal': Appeal, 'EvidenceItem': EvidenceItem, 'CallLog': CallLog}


class ClaimService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Claim:
        obj = Claim(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Claim | None:
        return self.db.get(Claim, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Claim).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Claim | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Claim | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'submitted': ['paid', 'denied'], 'denied': ['internal_appeal', 'abandoned'], 'internal_appeal': ['overturned', 'upheld', 'abandoned'], 'upheld': ['external_review', 'abandoned'], 'external_review': ['overturned', 'final_denial'], 'overturned': ['paid'], 'paid': [], 'final_denial': [], 'abandoned': ['denied']}
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

class DenialService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Denial:
        _v = data.get('claim_id')
        if _v is not None:
            _ref = self.db.get(Claim, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent claim_id')
            if getattr(_ref, 'status', None) not in ['submitted', 'denied', 'internal_appeal', 'upheld', 'external_review']:
                raise DomainRuleError('claim must exist and not be closed')
        obj = Denial(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Denial | None:
        return self.db.get(Denial, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Denial).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Denial | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class AppealService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Appeal:
        _v = data.get('claim_id')
        if _v is not None:
            _ref = self.db.get(Claim, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent claim_id')
            if getattr(_ref, 'status', None) not in ['denied', 'internal_appeal', 'upheld', 'external_review']:
                raise DomainRuleError('appeal requires a denied claim')
        obj = Appeal(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Appeal | None:
        return self.db.get(Appeal, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Appeal).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Appeal | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Appeal | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'drafting': ['filed'], 'filed': ['won', 'lost', 'no_response'], 'won': [], 'lost': [], 'no_response': ['filed']}
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

class EvidenceItemService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> EvidenceItem:
        _v = data.get('claim_id')
        if _v is not None:
            _ref = self.db.get(Claim, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent claim_id')
            if getattr(_ref, 'status', None) not in ['submitted', 'denied', 'internal_appeal', 'upheld', 'external_review', 'overturned']:
                raise DomainRuleError('evidence attaches to an open claim')
        obj = EvidenceItem(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> EvidenceItem | None:
        return self.db.get(EvidenceItem, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(EvidenceItem).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> EvidenceItem | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class CallLogService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> CallLog:
        obj = CallLog(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> CallLog | None:
        return self.db.get(CallLog, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(CallLog).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> CallLog | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

_SERVICES = {'Claim': ClaimService, 'Denial': DenialService, 'Appeal': AppealService, 'EvidenceItem': EvidenceItemService, 'CallLog': CallLogService}
