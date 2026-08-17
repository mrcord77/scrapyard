"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import TenancyCreate, TenancyUpdate, TenancyRead, EvidenceShotCreate, EvidenceShotUpdate, EvidenceShotRead, DeductionCreate, DeductionUpdate, DeductionRead, DisputeLetterCreate, DisputeLetterUpdate, DisputeLetterRead
from .services import TenancyService, EvidenceShotService, DeductionService, DisputeLetterService
from .services import WorkflowError
from .models import Tenancy, EvidenceShot, Deduction, DisputeLetter
from scrapyard.database.db_session import get_db  # wired to the real session factory
from fastapi import Header
from scrapyard.identity.session_manager import SessionManager

def current_user_id(x_session: str | None = Header(None, alias='X-Session'),
                    db: Session = Depends(get_db)) -> int:
    """Resolve the authenticated user from the X-Session header; 401 if absent/invalid."""
    uid = SessionManager(db).user_id_for(x_session) if x_session else None
    if not uid:
        raise HTTPException(401, 'authentication required')
    return uid

router = APIRouter()

# --- Tenancy ---
@router.get("/tenancies", response_model=list[TenancyRead])
def list_tenancies(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Tenancy).where(Tenancy.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/tenancies/{id_}", response_model=TenancyRead)
def get_tenancy(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = TenancyService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/tenancies", response_model=TenancyRead, status_code=201)
def create_tenancy(payload: TenancyCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = TenancyService(db).create(**data)
    db.commit(); return obj

@router.put("/tenancies/{id_}", response_model=TenancyRead)
def update_tenancy(id_: int, payload: TenancyUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = TenancyService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = TenancyService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/tenancies/{id_}", status_code=204)
def delete_tenancy(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = TenancyService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    TenancyService(db).delete(id_)
    db.commit()

@router.post("/tenancies/{id_}/transition", response_model=TenancyRead)
def transition_tenancy(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = TenancyService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    try:
        obj = TenancyService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- EvidenceShot ---
@router.get("/evidence_shots", response_model=list[EvidenceShotRead])
def list_evidence_shots(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(EvidenceShot).where(EvidenceShot.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/evidence_shots/{id_}", response_model=EvidenceShotRead)
def get_evidence_shot(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EvidenceShotService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/evidence_shots", response_model=EvidenceShotRead, status_code=201)
def create_evidence_shot(payload: EvidenceShotCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = EvidenceShotService(db).create(**data)
    db.commit(); return obj

@router.put("/evidence_shots/{id_}", response_model=EvidenceShotRead)
def update_evidence_shot(id_: int, payload: EvidenceShotUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EvidenceShotService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = EvidenceShotService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/evidence_shots/{id_}", status_code=204)
def delete_evidence_shot(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EvidenceShotService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    EvidenceShotService(db).delete(id_)
    db.commit()

# --- Deduction ---
@router.get("/deductions", response_model=list[DeductionRead])
def list_deductions(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Deduction).where(Deduction.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/deductions/{id_}", response_model=DeductionRead)
def get_deduction(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DeductionService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/deductions", response_model=DeductionRead, status_code=201)
def create_deduction(payload: DeductionCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = DeductionService(db).create(**data)
    db.commit(); return obj

@router.put("/deductions/{id_}", response_model=DeductionRead)
def update_deduction(id_: int, payload: DeductionUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DeductionService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = DeductionService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/deductions/{id_}", status_code=204)
def delete_deduction(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DeductionService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    DeductionService(db).delete(id_)
    db.commit()

@router.post("/deductions/{id_}/transition", response_model=DeductionRead)
def transition_deduction(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = DeductionService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    try:
        obj = DeductionService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- DisputeLetter ---
@router.get("/dispute_letters", response_model=list[DisputeLetterRead])
def list_dispute_letters(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(DisputeLetter).where(DisputeLetter.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/dispute_letters/{id_}", response_model=DisputeLetterRead)
def get_dispute_letter(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DisputeLetterService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/dispute_letters", response_model=DisputeLetterRead, status_code=201)
def create_dispute_letter(payload: DisputeLetterCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = DisputeLetterService(db).create(**data)
    db.commit(); return obj

@router.put("/dispute_letters/{id_}", response_model=DisputeLetterRead)
def update_dispute_letter(id_: int, payload: DisputeLetterUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DisputeLetterService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = DisputeLetterService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/dispute_letters/{id_}", status_code=204)
def delete_dispute_letter(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DisputeLetterService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    DisputeLetterService(db).delete(id_)
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
