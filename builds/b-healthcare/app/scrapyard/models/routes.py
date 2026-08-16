"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import PatientCreate, PatientUpdate, PatientRead, ProviderCreate, ProviderUpdate, ProviderRead, AppointmentCreate, AppointmentUpdate, AppointmentRead, EncounterCreate, EncounterUpdate, EncounterRead
from .services import PatientService, ProviderService, AppointmentService, EncounterService
from .models import Patient, Provider
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

# --- Patient ---
@router.get("/patients", response_model=list[PatientRead])
def list_patients(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Patient).where(Patient.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/patients/{id_}", response_model=PatientRead)
def get_patient(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = PatientService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/patients", response_model=PatientRead, status_code=201)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = PatientService(db).create(**data)
    _audit(db, action='patient.create', actor_user_id=uid, target=f'patient:{obj.id}')
    db.commit(); return obj

@router.put("/patients/{id_}", response_model=PatientRead)
def update_patient(id_: int, payload: PatientUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = PatientService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = PatientService(db).update(id_, **data)
    _audit(db, action='patient.update', actor_user_id=uid, target=f'patient:{id_}')
    db.commit(); return obj

@router.delete("/patients/{id_}", status_code=204)
def delete_patient(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = PatientService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    PatientService(db).delete(id_)
    _audit(db, action='patient.delete', actor_user_id=uid, target=f'patient:{id_}')
    db.commit()

# --- Provider ---
@router.get("/providers", response_model=list[ProviderRead])
def list_providers(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Provider).where(Provider.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/providers/{id_}", response_model=ProviderRead)
def get_provider(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProviderService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/providers", response_model=ProviderRead, status_code=201)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = ProviderService(db).create(**data)
    _audit(db, action='provider.create', actor_user_id=uid, target=f'provider:{obj.id}')
    db.commit(); return obj

@router.put("/providers/{id_}", response_model=ProviderRead)
def update_provider(id_: int, payload: ProviderUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProviderService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = ProviderService(db).update(id_, **data)
    _audit(db, action='provider.update', actor_user_id=uid, target=f'provider:{id_}')
    db.commit(); return obj

@router.delete("/providers/{id_}", status_code=204)
def delete_provider(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProviderService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    ProviderService(db).delete(id_)
    _audit(db, action='provider.delete', actor_user_id=uid, target=f'provider:{id_}')
    db.commit()

# --- Appointment ---
@router.get("/appointments", response_model=list[AppointmentRead])
def list_appointments(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return AppointmentService(db).list(limit=limit, offset=offset)

@router.get("/appointments/{id_}", response_model=AppointmentRead)
def get_appointment(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AppointmentService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/appointments", response_model=AppointmentRead, status_code=201)
def create_appointment(payload: AppointmentCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AppointmentService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/appointments/{id_}", response_model=AppointmentRead)
def update_appointment(id_: int, payload: AppointmentUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AppointmentService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/appointments/{id_}", status_code=204)
def delete_appointment(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not AppointmentService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Encounter ---
@router.get("/encounters", response_model=list[EncounterRead])
def list_encounters(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return EncounterService(db).list(limit=limit, offset=offset)

@router.get("/encounters/{id_}", response_model=EncounterRead)
def get_encounter(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EncounterService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/encounters", response_model=EncounterRead, status_code=201)
def create_encounter(payload: EncounterCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EncounterService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/encounters/{id_}", response_model=EncounterRead)
def update_encounter(id_: int, payload: EncounterUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EncounterService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/encounters/{id_}", status_code=204)
def delete_encounter(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not EncounterService(db).delete(id_): raise HTTPException(404)
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
