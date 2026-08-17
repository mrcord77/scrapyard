"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import ChildCreate, ChildUpdate, ChildRead, MeetingCreate, MeetingUpdate, MeetingRead, CorrespondenceCreate, CorrespondenceUpdate, CorrespondenceRead, ServiceEntryCreate, ServiceEntryUpdate, ServiceEntryRead, ActionItemCreate, ActionItemUpdate, ActionItemRead
from .services import ChildService, MeetingService, CorrespondenceService, ServiceEntryService, ActionItemService
from .services import WorkflowError
from .models import Child, Meeting, Correspondence, ServiceEntry, ActionItem
from scrapyard.database.db_session import get_db  # wired to the real session factory
from fastapi import Header
from scrapyard.identity.session_manager import SessionManager

from scrapyard.admin.audit_logs import record as _audit
def current_user_id(x_session: str | None = Header(None, alias='X-Session'),
                    db: Session = Depends(get_db)) -> int:
    """Resolve the authenticated user from the X-Session header; 401 if absent/invalid."""
    uid = SessionManager(db).user_id_for(x_session) if x_session else None
    if not uid:
        raise HTTPException(401, 'authentication required')
    return uid

router = APIRouter()

# --- Child ---
@router.get("/children", response_model=list[ChildRead])
def list_children(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Child).where(Child.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/children/{id_}", response_model=ChildRead)
def get_child(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ChildService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/children", response_model=ChildRead, status_code=201)
def create_child(payload: ChildCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = ChildService(db).create(**data)
    _audit(db, action='child.create', actor_user_id=uid, target=f'child:{obj.id}')
    db.commit(); return obj

@router.put("/children/{id_}", response_model=ChildRead)
def update_child(id_: int, payload: ChildUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ChildService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = ChildService(db).update(id_, **data)
    _audit(db, action='child.update', actor_user_id=uid, target=f'child:{id_}')
    db.commit(); return obj

@router.delete("/children/{id_}", status_code=204)
def delete_child(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ChildService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    ChildService(db).delete(id_)
    _audit(db, action='child.delete', actor_user_id=uid, target=f'child:{id_}')
    db.commit()

# --- Meeting ---
@router.get("/meetings", response_model=list[MeetingRead])
def list_meetings(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Meeting).where(Meeting.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/meetings/{id_}", response_model=MeetingRead)
def get_meeting(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MeetingService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/meetings", response_model=MeetingRead, status_code=201)
def create_meeting(payload: MeetingCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = MeetingService(db).create(**data)
    _audit(db, action='meeting.create', actor_user_id=uid, target=f'meeting:{obj.id}')
    db.commit(); return obj

@router.put("/meetings/{id_}", response_model=MeetingRead)
def update_meeting(id_: int, payload: MeetingUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MeetingService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = MeetingService(db).update(id_, **data)
    _audit(db, action='meeting.update', actor_user_id=uid, target=f'meeting:{id_}')
    db.commit(); return obj

@router.delete("/meetings/{id_}", status_code=204)
def delete_meeting(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MeetingService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    MeetingService(db).delete(id_)
    db.commit()

@router.post("/meetings/{id_}/transition", response_model=MeetingRead)
def transition_meeting(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = MeetingService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    try:
        obj = MeetingService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    _audit(db, action='meeting.update', actor_user_id=uid, target=f'meeting:{id_}')
    db.commit(); return obj

# --- Correspondence ---
@router.get("/correspondences", response_model=list[CorrespondenceRead])
def list_correspondences(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Correspondence).where(Correspondence.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/correspondences/{id_}", response_model=CorrespondenceRead)
def get_correspondence(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CorrespondenceService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/correspondences", response_model=CorrespondenceRead, status_code=201)
def create_correspondence(payload: CorrespondenceCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = CorrespondenceService(db).create(**data)
    _audit(db, action='correspondence.create', actor_user_id=uid, target=f'correspondence:{obj.id}')
    db.commit(); return obj

@router.put("/correspondences/{id_}", response_model=CorrespondenceRead)
def update_correspondence(id_: int, payload: CorrespondenceUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CorrespondenceService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = CorrespondenceService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/correspondences/{id_}", status_code=204)
def delete_correspondence(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CorrespondenceService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    CorrespondenceService(db).delete(id_)
    db.commit()

# --- ServiceEntry ---
@router.get("/service_entries", response_model=list[ServiceEntryRead])
def list_service_entries(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(ServiceEntry).where(ServiceEntry.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/service_entries/{id_}", response_model=ServiceEntryRead)
def get_service_entry(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ServiceEntryService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/service_entries", response_model=ServiceEntryRead, status_code=201)
def create_service_entry(payload: ServiceEntryCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = ServiceEntryService(db).create(**data)
    _audit(db, action='service_entry.create', actor_user_id=uid, target=f'service_entry:{obj.id}')
    db.commit(); return obj

@router.put("/service_entries/{id_}", response_model=ServiceEntryRead)
def update_service_entry(id_: int, payload: ServiceEntryUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ServiceEntryService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = ServiceEntryService(db).update(id_, **data)
    _audit(db, action='service_entry.update', actor_user_id=uid, target=f'service_entry:{id_}')
    db.commit(); return obj

@router.delete("/service_entries/{id_}", status_code=204)
def delete_service_entry(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ServiceEntryService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    ServiceEntryService(db).delete(id_)
    _audit(db, action='service_entry.delete', actor_user_id=uid, target=f'service_entry:{id_}')
    db.commit()

# --- ActionItem ---
@router.get("/action_items", response_model=list[ActionItemRead])
def list_action_items(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(ActionItem).where(ActionItem.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/action_items/{id_}", response_model=ActionItemRead)
def get_action_item(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ActionItemService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/action_items", response_model=ActionItemRead, status_code=201)
def create_action_item(payload: ActionItemCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = ActionItemService(db).create(**data)
    _audit(db, action='action_item.create', actor_user_id=uid, target=f'action_item:{obj.id}')
    db.commit(); return obj

@router.put("/action_items/{id_}", response_model=ActionItemRead)
def update_action_item(id_: int, payload: ActionItemUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ActionItemService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = ActionItemService(db).update(id_, **data)
    _audit(db, action='action_item.update', actor_user_id=uid, target=f'action_item:{id_}')
    db.commit(); return obj

@router.delete("/action_items/{id_}", status_code=204)
def delete_action_item(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ActionItemService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    ActionItemService(db).delete(id_)
    _audit(db, action='action_item.delete', actor_user_id=uid, target=f'action_item:{id_}')
    db.commit()

@router.post("/action_items/{id_}/transition", response_model=ActionItemRead)
def transition_action_item(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = ActionItemService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    try:
        obj = ActionItemService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    _audit(db, action='action_item.update', actor_user_id=uid, target=f'action_item:{id_}')
    db.commit(); return obj

# --- data subject rights (GDPR/CCPA: access, portability, erasure) ---
# Module-scope import so DeletionRecord registers on the ORM base BEFORE the
# boot-time create_all — a lazy in-route import would leave its table missing.
import scrapyard.compliance.account_deletion  # noqa: F401  (model registration)
@router.get("/privacy/export")
def privacy_export(db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    """Export everything stored about the authenticated user (domain + identity)."""
    from . import privacy as _p
    from scrapyard.compliance.data_export import export_user_data as _identity_export
    return {'user_id': uid, 'domain_data': _p.export_user_data(db, uid),
            'identity_data': _identity_export(db, uid)}

@router.get("/privacy/export/stream")
def privacy_export_stream(db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    """Stream the user's domain data as NDJSON (one record per line), constant-
    memory via a server-side cursor — portability that scales to large accounts
    without buffering the whole export in memory."""
    from fastapi.responses import StreamingResponse
    from . import privacy as _p
    return StreamingResponse(_p.stream_user_data(db, uid), media_type='application/x-ndjson',
                             headers={'Content-Disposition': 'attachment; filename="export.ndjson"'})

@router.post("/privacy/delete-account")
def privacy_delete_account(db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    """Erase the authenticated user: domain-owned rows first, then identity
    (sessions + user record), with an audit record. Right to erasure."""
    from . import privacy as _p
    from scrapyard.compliance.account_deletion import delete_account as _delete_identity
    domain = _p.delete_user_data(db, uid)   # domain tables (own ORM registry)
    # confirm=True: without it delete_account is a SAFE-BY-DEFAULT dry run and
    # the user row + sessions would survive (deleted account could log back in).
    identity = _delete_identity(db, uid, confirm=True)  # library identity tables + user row
    db.commit()
    return {'deleted': True, 'domain': domain, 'identity': identity}
