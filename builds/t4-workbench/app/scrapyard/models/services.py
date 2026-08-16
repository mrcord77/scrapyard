"""Generated services: CRUD + domain-rule enforcement."""
from __future__ import annotations
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import ResearchDoc, Note, Experiment, Run, Tag, ResearchDocTags, ExperimentTags


from scrapyard.api.domain_errors import WorkflowError, DomainRuleError


_MODELS = {'ResearchDoc': ResearchDoc, 'Note': Note, 'Experiment': Experiment, 'Run': Run, 'Tag': Tag}


class ResearchDocService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> ResearchDoc:
        obj = ResearchDoc(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> ResearchDoc | None:
        return self.db.get(ResearchDoc, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(ResearchDoc).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> ResearchDoc | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> ResearchDoc | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'inbox': ['reading', 'archived'], 'reading': ['annotated', 'archived'], 'annotated': ['archived'], 'archived': ['inbox']}
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

class NoteService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Note:
        _v = data.get('doc_id')
        if _v is not None:
            _ref = self.db.get(ResearchDoc, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent doc_id')
            if getattr(_ref, 'status', None) not in ['inbox', 'reading', 'annotated']:
                raise DomainRuleError('document must exist and not be archived')
        obj = Note(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Note | None:
        return self.db.get(Note, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Note).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Note | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

class ExperimentService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Experiment:
        obj = Experiment(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Experiment | None:
        return self.db.get(Experiment, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Experiment).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Experiment | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Experiment | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'draft': ['running', 'abandoned'], 'running': ['analyzing', 'failed', 'abandoned'], 'analyzing': ['concluded', 'running'], 'concluded': [], 'failed': ['draft'], 'abandoned': ['draft']}
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

class RunService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **data) -> Run:
        _v = data.get('experiment_id')
        if _v is not None:
            _ref = self.db.get(Experiment, _v)
            if _ref is None:
                raise DomainRuleError('nonexistent experiment_id')
            if getattr(_ref, 'status', None) not in ['running', 'analyzing']:
                raise DomainRuleError('experiment must be running or analyzing')
        obj = Run(**data)
        self.db.add(obj); self.db.flush(); return obj

    def get(self, id_: int) -> Run | None:
        return self.db.get(Run, id_)

    def list(self, *, limit: int = 50, offset: int = 0):
        return list(self.db.scalars(select(Run).limit(limit).offset(offset)))

    def update(self, id_: int, **data) -> Run | None:
        obj = self.get(id_)
        if not obj: return None
        for k, v in data.items(): setattr(obj, k, v)
        self.db.flush(); return obj

    def delete(self, id_: int) -> bool:
        obj = self.get(id_)
        if not obj: return False
        self.db.delete(obj); self.db.flush(); return True

    def transition(self, id_: int, to_state: str) -> Run | None:
        """Enforce the state machine: only declared transitions are allowed, and
        each target state's guards must hold. Guards may check a field on this row
        (equals) OR a related row's status (ref/entity/field/in). Raises WorkflowError."""
        obj = self.get(id_)
        if not obj: return None
        _T = {'queued': ['executing', 'cancelled'], 'executing': ['succeeded', 'failed', 'cancelled'], 'succeeded': [], 'failed': ['queued'], 'cancelled': []}
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

class ResearchDocTagsLinks:
    """Many-to-many link service for research_doc_tags (ResearchDoc <-> Tag)."""
    def __init__(self, db: Session):
        self.db = db

    def attach(self, left_id: int, right_id: int):
        if self.db.get(ResearchDoc, left_id) is None:
            raise DomainRuleError('nonexistent research_doc_id')
        if self.db.get(Tag, right_id) is None:
            raise DomainRuleError('nonexistent tag_id')
        _ex = self.db.scalar(select(ResearchDocTags).where(ResearchDocTags.research_doc_id == left_id, ResearchDocTags.tag_id == right_id))
        if _ex is not None:
            return _ex  # idempotent: already linked
        _link = ResearchDocTags(**{'research_doc_id': left_id, 'tag_id': right_id})
        self.db.add(_link); self.db.flush(); return _link

    def detach(self, left_id: int, right_id: int) -> bool:
        self.db.execute(delete(ResearchDocTags).where(ResearchDocTags.research_doc_id == left_id, ResearchDocTags.tag_id == right_id))
        self.db.flush(); return True

    def list_right(self, left_id: int):
        _ids = list(self.db.scalars(select(ResearchDocTags.tag_id).where(ResearchDocTags.research_doc_id == left_id)))
        return list(self.db.scalars(select(Tag).where(Tag.id.in_(_ids)))) if _ids else []

    def list_left(self, right_id: int):
        _ids = list(self.db.scalars(select(ResearchDocTags.research_doc_id).where(ResearchDocTags.tag_id == right_id)))
        return list(self.db.scalars(select(ResearchDoc).where(ResearchDoc.id.in_(_ids)))) if _ids else []

class ExperimentTagsLinks:
    """Many-to-many link service for experiment_tags (Experiment <-> Tag)."""
    def __init__(self, db: Session):
        self.db = db

    def attach(self, left_id: int, right_id: int):
        if self.db.get(Experiment, left_id) is None:
            raise DomainRuleError('nonexistent experiment_id')
        if self.db.get(Tag, right_id) is None:
            raise DomainRuleError('nonexistent tag_id')
        _ex = self.db.scalar(select(ExperimentTags).where(ExperimentTags.experiment_id == left_id, ExperimentTags.tag_id == right_id))
        if _ex is not None:
            return _ex  # idempotent: already linked
        _link = ExperimentTags(**{'experiment_id': left_id, 'tag_id': right_id})
        self.db.add(_link); self.db.flush(); return _link

    def detach(self, left_id: int, right_id: int) -> bool:
        self.db.execute(delete(ExperimentTags).where(ExperimentTags.experiment_id == left_id, ExperimentTags.tag_id == right_id))
        self.db.flush(); return True

    def list_right(self, left_id: int):
        _ids = list(self.db.scalars(select(ExperimentTags.tag_id).where(ExperimentTags.experiment_id == left_id)))
        return list(self.db.scalars(select(Tag).where(Tag.id.in_(_ids)))) if _ids else []

    def list_left(self, right_id: int):
        _ids = list(self.db.scalars(select(ExperimentTags.experiment_id).where(ExperimentTags.tag_id == right_id)))
        return list(self.db.scalars(select(Experiment).where(Experiment.id.in_(_ids)))) if _ids else []

_SERVICES = {'ResearchDoc': ResearchDocService, 'Note': NoteService, 'Experiment': ExperimentService, 'Run': RunService, 'Tag': TagService}
