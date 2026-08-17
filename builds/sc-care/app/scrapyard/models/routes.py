"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import CareRecipientCreate, CareRecipientUpdate, CareRecipientRead, CareTaskCreate, CareTaskUpdate, CareTaskRead, MedicationCreate, MedicationUpdate, MedicationRead, DoseLogCreate, DoseLogUpdate, DoseLogRead, AppointmentCreate, AppointmentUpdate, AppointmentRead, UpdateCreate, UpdateUpdate, UpdateRead
from .services import CareRecipientService, CareTaskService, MedicationService, DoseLogService, AppointmentService, UpdateService
from .services import WorkflowError
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

# --- CareRecipient ---
@router.get("/care_recipients", response_model=list[CareRecipientRead])
def list_care_recipients(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return CareRecipientService(db).list(limit=limit, offset=offset)

@router.get("/care_recipients/{id_}", response_model=CareRecipientRead)
def get_care_recipient(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CareRecipientService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/care_recipients", response_model=CareRecipientRead, status_code=201)
def create_care_recipient(payload: CareRecipientCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CareRecipientService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/care_recipients/{id_}", response_model=CareRecipientRead)
def update_care_recipient(id_: int, payload: CareRecipientUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CareRecipientService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/care_recipients/{id_}", status_code=204)
def delete_care_recipient(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not CareRecipientService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- CareTask ---
@router.get("/care_tasks", response_model=list[CareTaskRead])
def list_care_tasks(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return CareTaskService(db).list(limit=limit, offset=offset)

@router.get("/care_tasks/{id_}", response_model=CareTaskRead)
def get_care_task(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CareTaskService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/care_tasks", response_model=CareTaskRead, status_code=201)
def create_care_task(payload: CareTaskCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CareTaskService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/care_tasks/{id_}", response_model=CareTaskRead)
def update_care_task(id_: int, payload: CareTaskUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CareTaskService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/care_tasks/{id_}", status_code=204)
def delete_care_task(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not CareTaskService(db).delete(id_): raise HTTPException(404)
    db.commit()

@router.post("/care_tasks/{id_}/transition", response_model=CareTaskRead)
def transition_care_task(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = CareTaskService(db).get(id_)
    if not obj:
        raise HTTPException(404)
    try:
        obj = CareTaskService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- Medication ---
@router.get("/medications", response_model=list[MedicationRead])
def list_medications(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return MedicationService(db).list(limit=limit, offset=offset)

@router.get("/medications/{id_}", response_model=MedicationRead)
def get_medication(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MedicationService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/medications", response_model=MedicationRead, status_code=201)
def create_medication(payload: MedicationCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MedicationService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/medications/{id_}", response_model=MedicationRead)
def update_medication(id_: int, payload: MedicationUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MedicationService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/medications/{id_}", status_code=204)
def delete_medication(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not MedicationService(db).delete(id_): raise HTTPException(404)
    db.commit()

@router.post("/medications/{id_}/transition", response_model=MedicationRead)
def transition_medication(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = MedicationService(db).get(id_)
    if not obj:
        raise HTTPException(404)
    try:
        obj = MedicationService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- DoseLog ---
@router.get("/dose_logs", response_model=list[DoseLogRead])
def list_dose_logs(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return DoseLogService(db).list(limit=limit, offset=offset)

@router.get("/dose_logs/{id_}", response_model=DoseLogRead)
def get_dose_log(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DoseLogService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/dose_logs", response_model=DoseLogRead, status_code=201)
def create_dose_log(payload: DoseLogCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DoseLogService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/dose_logs/{id_}", response_model=DoseLogRead)
def update_dose_log(id_: int, payload: DoseLogUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = DoseLogService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/dose_logs/{id_}", status_code=204)
def delete_dose_log(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not DoseLogService(db).delete(id_): raise HTTPException(404)
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

@router.post("/appointments/{id_}/transition", response_model=AppointmentRead)
def transition_appointment(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = AppointmentService(db).get(id_)
    if not obj:
        raise HTTPException(404)
    try:
        obj = AppointmentService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- Update ---
@router.get("/updates", response_model=list[UpdateRead])
def list_updates(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return UpdateService(db).list(limit=limit, offset=offset)

@router.get("/updates/{id_}", response_model=UpdateRead)
def get_update(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = UpdateService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/updates", response_model=UpdateRead, status_code=201)
def create_update(payload: UpdateCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = UpdateService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/updates/{id_}", response_model=UpdateRead)
def update_update(id_: int, payload: UpdateUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = UpdateService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/updates/{id_}", status_code=204)
def delete_update(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not UpdateService(db).delete(id_): raise HTTPException(404)
    db.commit()
