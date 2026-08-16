"""Generated services: CRUD + domain-rule enforcement."""
from __future__ import annotations
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import Project, Task, Label, TaskLabels


from scrapyard.api.domain_errors import WorkflowError, DomainRuleError


_MODELS = {'Project': Project, 'Task': Task, 'Label': Label}


class ProjectService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Project:
        obj = Project(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Project | None:
        return self.db.get(Project, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Project).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Project | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Project | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'active': ['archived'], 'archived': ['active']}
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

class TaskService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Task:
        _v = data.get('project_id')
        if _v is not None:
            _ref = self.db.get(Project, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent project_id')
            if getattr(_ref, 'status', None) not in ['active']:
                raise DomainRuleError('project must exist and be active')
        obj = Task(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Task | None:
        return self.db.get(Task, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Task).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Task | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Task | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'todo': ['doing', 'cancelled'], 'doing': ['todo', 'blocked', 'done', 'cancelled'], 'blocked': ['doing', 'cancelled'], 'done': [], 'cancelled': ['todo']}
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

class LabelService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Label:
        obj = Label(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Label | None:
        return self.db.get(Label, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Label).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Label | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class TaskLabelsLinks:
    """Many-to-many link service for task_labels (Task <-> Label)."""
    def __init__(self, db: Session):
        self.db = db

    def attach(self, left_id: int, right_id: int):
        if self.db.get(Task, left_id) is None:
            raise DomainRuleError('nonexistent task_id')
        if self.db.get(Label, right_id) is None:
            raise DomainRuleError('nonexistent label_id')
        _ex = self.db.scalar(select(TaskLabels).where(TaskLabels.task_id == left_id, TaskLabels.label_id == right_id))
        if _ex is not None:
            return _ex  # idempotent: already linked
        _link = TaskLabels(**{'task_id': left_id, 'label_id': right_id})
        self.db.add(_link); self.db.flush(); return _link

    def detach(self, left_id: int, right_id: int) -> bool:
        self.db.execute(delete(TaskLabels).where(TaskLabels.task_id == left_id, TaskLabels.label_id == right_id))
        self.db.flush(); return True

    def list_right(self, left_id: int):
        _ids = list(self.db.scalars(select(TaskLabels.label_id).where(TaskLabels.task_id == left_id)))
        return list(self.db.scalars(select(Label).where(Label.id.in_(_ids)))) if _ids else []

    def list_left(self, right_id: int):
        _ids = list(self.db.scalars(select(TaskLabels.task_id).where(TaskLabels.label_id == right_id)))
        return list(self.db.scalars(select(Task).where(Task.id.in_(_ids)))) if _ids else []

_SERVICES = {'Project': ProjectService, 'Task': TaskService, 'Label': LabelService}
