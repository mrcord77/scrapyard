"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import ClaimCreate, ClaimUpdate, ClaimRead, DenialCreate, DenialUpdate, DenialRead, AppealCreate, AppealUpdate, AppealRead, EvidenceItemCreate, EvidenceItemUpdate, EvidenceItemRead, CallLogCreate, CallLogUpdate, CallLogRead
from .services import ClaimService, DenialService, AppealService, EvidenceItemService, CallLogService
from .services import WorkflowError
from .models import Claim, Denial, Appeal, EvidenceItem, CallLog
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

# --- Claim ---
@router.get("/claims", response_model=list[ClaimRead])
def list_claims(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Claim).where(Claim.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/claims/{id_}", response_model=ClaimRead)
def get_claim(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ClaimService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/claims", response_model=ClaimRead, status_code=201)
def create_claim(payload: ClaimCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = ClaimService(db).create(**data)
    _audit(db, action='claim.create', actor_user_id=uid, target=f'claim:{obj.id}')
    db.commit(); return obj

@router.put("/claims/{id_}", response_model=ClaimRead)
def update_claim(id_: int, payload: ClaimUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ClaimService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = ClaimService(db).update(id_, **data)
    _audit(db, action='claim.update', actor_user_id=uid, target=f'claim:{id_}')
    db.commit(); return obj

@router.delete("/claims/{id_}", status_code=204)
def delete_claim(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ClaimService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    ClaimService(db).delete(id_)
    _audit(db, action='claim.delete', actor_user_id=uid, target=f'claim:{id_}')
    db.commit()

@router.post("/claims/{id_}/transition", response_model=ClaimRead)
def transition_claim(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = ClaimService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    try:
        obj = ClaimService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    _audit(db, action='claim.update', actor_user_id=uid, target=f'claim:{id_}')
    db.commit(); return obj

# --- Denial ---
@router.get("/denials", response_model=list[DenialRead])
def list_denials(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Denial).where(Denial.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/denials/{id_}", response_model=DenialRead)
def get_denial(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DenialService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/denials", response_model=DenialRead, status_code=201)
def create_denial(payload: DenialCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = DenialService(db).create(**data)
    _audit(db, action='denial.create', actor_user_id=uid, target=f'denial:{obj.id}')
    db.commit(); return obj

@router.put("/denials/{id_}", response_model=DenialRead)
def update_denial(id_: int, payload: DenialUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DenialService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = DenialService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/denials/{id_}", status_code=204)
def delete_denial(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DenialService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    DenialService(db).delete(id_)
    _audit(db, action='denial.delete', actor_user_id=uid, target=f'denial:{id_}')
    db.commit()

# --- Appeal ---
@router.get("/appeals", response_model=list[AppealRead])
def list_appeals(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Appeal).where(Appeal.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/appeals/{id_}", response_model=AppealRead)
def get_appeal(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AppealService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/appeals", response_model=AppealRead, status_code=201)
def create_appeal(payload: AppealCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = AppealService(db).create(**data)
    _audit(db, action='appeal.create', actor_user_id=uid, target=f'appeal:{obj.id}')
    db.commit(); return obj

@router.put("/appeals/{id_}", response_model=AppealRead)
def update_appeal(id_: int, payload: AppealUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AppealService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = AppealService(db).update(id_, **data)
    _audit(db, action='appeal.update', actor_user_id=uid, target=f'appeal:{id_}')
    db.commit(); return obj

@router.delete("/appeals/{id_}", status_code=204)
def delete_appeal(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AppealService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    AppealService(db).delete(id_)
    _audit(db, action='appeal.delete', actor_user_id=uid, target=f'appeal:{id_}')
    db.commit()

@router.post("/appeals/{id_}/transition", response_model=AppealRead)
def transition_appeal(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = AppealService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    try:
        obj = AppealService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    _audit(db, action='appeal.update', actor_user_id=uid, target=f'appeal:{id_}')
    db.commit(); return obj

# --- EvidenceItem ---
@router.get("/evidence_items", response_model=list[EvidenceItemRead])
def list_evidence_items(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(EvidenceItem).where(EvidenceItem.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/evidence_items/{id_}", response_model=EvidenceItemRead)
def get_evidence_item(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EvidenceItemService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/evidence_items", response_model=EvidenceItemRead, status_code=201)
def create_evidence_item(payload: EvidenceItemCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = EvidenceItemService(db).create(**data)
    _audit(db, action='evidence_item.create', actor_user_id=uid, target=f'evidence_item:{obj.id}')
    db.commit(); return obj

@router.put("/evidence_items/{id_}", response_model=EvidenceItemRead)
def update_evidence_item(id_: int, payload: EvidenceItemUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EvidenceItemService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = EvidenceItemService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/evidence_items/{id_}", status_code=204)
def delete_evidence_item(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EvidenceItemService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    EvidenceItemService(db).delete(id_)
    _audit(db, action='evidence_item.delete', actor_user_id=uid, target=f'evidence_item:{id_}')
    db.commit()

# --- CallLog ---
@router.get("/call_logs", response_model=list[CallLogRead])
def list_call_logs(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(CallLog).where(CallLog.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/call_logs/{id_}", response_model=CallLogRead)
def get_call_log(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CallLogService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/call_logs", response_model=CallLogRead, status_code=201)
def create_call_log(payload: CallLogCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = CallLogService(db).create(**data)
    _audit(db, action='call_log.create', actor_user_id=uid, target=f'call_log:{obj.id}')
    db.commit(); return obj

@router.put("/call_logs/{id_}", response_model=CallLogRead)
def update_call_log(id_: int, payload: CallLogUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CallLogService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = CallLogService(db).update(id_, **data)
    _audit(db, action='call_log.update', actor_user_id=uid, target=f'call_log:{id_}')
    db.commit(); return obj

@router.delete("/call_logs/{id_}", status_code=204)
def delete_call_log(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CallLogService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    CallLogService(db).delete(id_)
    _audit(db, action='call_log.delete', actor_user_id=uid, target=f'call_log:{id_}')
    db.commit()

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
