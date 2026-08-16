"""Generated services: CRUD + domain-rule enforcement."""
from __future__ import annotations
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import Member, Tool, Reservation, Incident, MaintenanceRecord, Tag, ToolTags


from scrapyard.api.domain_errors import WorkflowError, DomainRuleError


_MODELS = {'Member': Member, 'Tool': Tool, 'Reservation': Reservation, 'Incident': Incident, 'MaintenanceRecord': MaintenanceRecord, 'Tag': Tag}


class MemberService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Member:
        obj = Member(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Member | None:
        return self.db.get(Member, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Member).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Member | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Member | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'active': ['suspended', 'expired', 'banned'], 'suspended': ['active'], 'expired': ['active'], 'banned': []}
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

class ToolService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Tool:
        obj = Tool(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Tool | None:
        return self.db.get(Tool, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Tool).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Tool | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Tool | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'available': ['reserved', 'checked_out', 'maintenance', 'broken', 'retired'], 'reserved': ['available', 'checked_out'], 'checked_out': ['available', 'maintenance', 'broken'], 'maintenance': ['available', 'retired'], 'broken': ['maintenance', 'retired']}
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

class ReservationService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Reservation:
        _v = data.get('member_id')
        if _v is not None:
            _ref = self.db.get(Member, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent member_id')
            if getattr(_ref, 'status', None) not in ['active']:
                raise DomainRuleError('member must exist and be active')
        _v = data.get('tool_id')
        if _v is not None:
            _ref = self.db.get(Tool, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent tool_id')
            if getattr(_ref, 'status', None) not in ['available']:
                raise DomainRuleError('tool must exist and be available')
        if data.get('tool_id') is not None and data.get('start_at') is not None and data.get('end_at') is not None:
            _conf = self.db.scalar(select(Reservation).where(
                Reservation.tool_id == data['tool_id'], Reservation.status.in_(['requested', 'approved', 'reserved', 'checked_out']),
                Reservation.start_at < data['end_at'], Reservation.end_at > data['start_at']))
            if _conf is not None:
                raise DomainRuleError('tool already reserved for an overlapping period')
        obj = Reservation(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Reservation | None:
        return self.db.get(Reservation, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Reservation).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Reservation | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Reservation | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'requested': ['approved', 'cancelled', 'denied', 'expired'], 'approved': ['reserved', 'cancelled', 'expired'], 'reserved': ['checked_out', 'cancelled', 'expired'], 'checked_out': ['returned', 'returned_damaged'], 'returned': [], 'returned_damaged': [], 'cancelled': [], 'denied': [], 'expired': []}
        _G = {'checked_out': [{'ref': 'tool_id', 'entity': 'Tool', 'field': 'status', 'in': ['available', 'reserved'], 'error': 'cannot check out: tool is not available'}, {'ref': 'member_id', 'entity': 'Member', 'field': 'status', 'in': ['active'], 'error': 'cannot check out: member is not active'}]}
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
        _E = {'checked_out': [{'set_related': {'ref': 'tool_id', 'entity': 'Tool', 'field': 'status', 'value': 'checked_out', 'guarded': True}}], 'returned': [{'set_related': {'ref': 'tool_id', 'entity': 'Tool', 'field': 'status', 'value': 'available', 'guarded': True}}], 'returned_damaged': [{'set_related': {'ref': 'tool_id', 'entity': 'Tool', 'field': 'status', 'value': 'maintenance', 'guarded': True}}, {'create': {'entity': 'Incident', 'values': {'tool_id': '$tool_id', 'reservation_id': '$id', 'note': 'damaged on return'}}}, {'create': {'entity': 'MaintenanceRecord', 'values': {'tool_id': '$tool_id', 'status': 'open'}}}]}
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

    def sweep(self, now=None):
        """Time-based transitions: advance rows whose deadline field has passed.
        Each move is applied THROUGH transition(), so the state machine's guards
        and effects still hold; a row whose guard is unmet is skipped. 'now'
        defaults to datetime.utcnow() (datetime deadlines); pass an explicit value
        (e.g. a day cursor) for non-datetime deadline fields. Returns moved ids."""
        from datetime import datetime as _dt
        _TT = [{'from': 'requested', 'to': 'expired', 'when': 'end_at'}, {'from': 'approved', 'to': 'expired', 'when': 'end_at'}, {'from': 'reserved', 'to': 'expired', 'when': 'end_at'}]
        _done = []
        for _t in _TT:
            _cmp = now if now is not None else _dt.utcnow()
            _q = select(Reservation).where(getattr(Reservation, 'status') == _t['from'], getattr(Reservation, _t['when']).is_not(None), getattr(Reservation, _t['when']) < _cmp)
            for _r in list(self.db.scalars(_q)):
                try:
                    self.transition(_r.id, _t['to']); _done.append(_r.id)
                except WorkflowError:
                    pass  # guard not satisfied for this row -> leave it
        self.db.flush(); return _done

class IncidentService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Incident:
        obj = Incident(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Incident | None:
        return self.db.get(Incident, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Incident).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Incident | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class MaintenanceRecordService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> MaintenanceRecord:
        obj = MaintenanceRecord(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> MaintenanceRecord | None:
        return self.db.get(MaintenanceRecord, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(MaintenanceRecord).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> MaintenanceRecord | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> MaintenanceRecord | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'open': ['completed'], 'completed': []}
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
        _E = {'completed': [{'set_related': {'ref': 'tool_id', 'entity': 'Tool', 'field': 'status', 'value': 'available', 'guarded': True}}]}
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

class TagService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Tag:
        obj = Tag(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Tag | None:
        return self.db.get(Tag, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Tag).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Tag | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class ToolTagsLinks:
    """Many-to-many link service for tool_tags (Tool <-> Tag)."""
    def __init__(self, db: Session):
        self.db = db

    def attach(self, left_id: int, right_id: int):
        if self.db.get(Tool, left_id) is None:
            raise DomainRuleError('nonexistent tool_id')
        if self.db.get(Tag, right_id) is None:
            raise DomainRuleError('nonexistent tag_id')
        _ex = self.db.scalar(select(ToolTags).where(ToolTags.tool_id == left_id, ToolTags.tag_id == right_id))
        if _ex is not None:
            return _ex  # idempotent: already linked
        _link = ToolTags(**{'tool_id': left_id, 'tag_id': right_id})
        self.db.add(_link); self.db.flush(); return _link

    def detach(self, left_id: int, right_id: int) -> bool:
        self.db.execute(delete(ToolTags).where(ToolTags.tool_id == left_id, ToolTags.tag_id == right_id))
        self.db.flush(); return True

    def list_right(self, left_id: int):
        _ids = list(self.db.scalars(select(ToolTags.tag_id).where(ToolTags.tool_id == left_id)))
        return list(self.db.scalars(select(Tag).where(Tag.id.in_(_ids)))) if _ids else []

    def list_left(self, right_id: int):
        _ids = list(self.db.scalars(select(ToolTags.tool_id).where(ToolTags.tag_id == right_id)))
        return list(self.db.scalars(select(Tool).where(Tool.id.in_(_ids)))) if _ids else []

_SERVICES = {'Member': MemberService, 'Tool': ToolService, 'Reservation': ReservationService, 'Incident': IncidentService, 'MaintenanceRecord': MaintenanceRecordService, 'Tag': TagService}
