"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import MemberCreate, MemberUpdate, MemberRead, ToolCreate, ToolUpdate, ToolRead, ReservationCreate, ReservationUpdate, ReservationRead, IncidentCreate, IncidentUpdate, IncidentRead, MaintenanceRecordCreate, MaintenanceRecordUpdate, MaintenanceRecordRead, TagCreate, TagUpdate, TagRead
from .services import MemberService, ToolService, ReservationService, IncidentService, MaintenanceRecordService, TagService
from .services import WorkflowError
from datetime import datetime  # for time-based sweep deadlines
from .services import ToolTagsLinks
from scrapyard.database.db_session import get_db  # wired to the real session factory

router = APIRouter()

# --- Member ---
@router.get("/members", response_model=list[MemberRead])
def list_members(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return MemberService(db).list(limit=limit, offset=offset)

@router.get("/members/{id_}", response_model=MemberRead)
def get_member(id_: int, db: Session = Depends(get_db)):
    obj = MemberService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/members", response_model=MemberRead, status_code=201)
def create_member(payload: MemberCreate, db: Session = Depends(get_db)):
    obj = MemberService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/members/{id_}", response_model=MemberRead)
def update_member(id_: int, payload: MemberUpdate, db: Session = Depends(get_db)):
    obj = MemberService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/members/{id_}", status_code=204)
def delete_member(id_: int, db: Session = Depends(get_db)):
    if not MemberService(db).delete(id_): raise HTTPException(404)
    db.commit()

@router.post("/members/{id_}/transition", response_model=MemberRead)
def transition_member(id_: int, payload: dict, db: Session = Depends(get_db)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = MemberService(db).get(id_)
    if not obj:
        raise HTTPException(404)
    try:
        obj = MemberService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- Tool ---
@router.get("/tools", response_model=list[ToolRead])
def list_tools(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return ToolService(db).list(limit=limit, offset=offset)

@router.get("/tools/{id_}", response_model=ToolRead)
def get_tool(id_: int, db: Session = Depends(get_db)):
    obj = ToolService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/tools", response_model=ToolRead, status_code=201)
def create_tool(payload: ToolCreate, db: Session = Depends(get_db)):
    obj = ToolService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/tools/{id_}", response_model=ToolRead)
def update_tool(id_: int, payload: ToolUpdate, db: Session = Depends(get_db)):
    obj = ToolService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/tools/{id_}", status_code=204)
def delete_tool(id_: int, db: Session = Depends(get_db)):
    if not ToolService(db).delete(id_): raise HTTPException(404)
    db.commit()

@router.post("/tools/{id_}/transition", response_model=ToolRead)
def transition_tool(id_: int, payload: dict, db: Session = Depends(get_db)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = ToolService(db).get(id_)
    if not obj:
        raise HTTPException(404)
    try:
        obj = ToolService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- Reservation ---
@router.get("/reservations", response_model=list[ReservationRead])
def list_reservations(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return ReservationService(db).list(limit=limit, offset=offset)

@router.get("/reservations/{id_}", response_model=ReservationRead)
def get_reservation(id_: int, db: Session = Depends(get_db)):
    obj = ReservationService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/reservations", response_model=ReservationRead, status_code=201)
def create_reservation(payload: ReservationCreate, db: Session = Depends(get_db)):
    obj = ReservationService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/reservations/{id_}", response_model=ReservationRead)
def update_reservation(id_: int, payload: ReservationUpdate, db: Session = Depends(get_db)):
    obj = ReservationService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/reservations/{id_}", status_code=204)
def delete_reservation(id_: int, db: Session = Depends(get_db)):
    if not ReservationService(db).delete(id_): raise HTTPException(404)
    db.commit()

@router.post("/reservations/{id_}/transition", response_model=ReservationRead)
def transition_reservation(id_: int, payload: dict, db: Session = Depends(get_db)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = ReservationService(db).get(id_)
    if not obj:
        raise HTTPException(404)
    try:
        obj = ReservationService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

@router.post("/reservations/sweep")
def sweep_reservations(now: int | None = None, db: Session = Depends(get_db)):
    """Scheduler-driven: advance rows whose deadline has passed (call periodically)."""
    ids = ReservationService(db).sweep(now=now); db.commit()
    return {'transitioned': ids, 'count': len(ids)}

# --- Incident ---
@router.get("/incidents", response_model=list[IncidentRead])
def list_incidents(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return IncidentService(db).list(limit=limit, offset=offset)

@router.get("/incidents/{id_}", response_model=IncidentRead)
def get_incident(id_: int, db: Session = Depends(get_db)):
    obj = IncidentService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/incidents", response_model=IncidentRead, status_code=201)
def create_incident(payload: IncidentCreate, db: Session = Depends(get_db)):
    obj = IncidentService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/incidents/{id_}", response_model=IncidentRead)
def update_incident(id_: int, payload: IncidentUpdate, db: Session = Depends(get_db)):
    obj = IncidentService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/incidents/{id_}", status_code=204)
def delete_incident(id_: int, db: Session = Depends(get_db)):
    if not IncidentService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- MaintenanceRecord ---
@router.get("/maintenance_records", response_model=list[MaintenanceRecordRead])
def list_maintenance_records(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return MaintenanceRecordService(db).list(limit=limit, offset=offset)

@router.get("/maintenance_records/{id_}", response_model=MaintenanceRecordRead)
def get_maintenance_record(id_: int, db: Session = Depends(get_db)):
    obj = MaintenanceRecordService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/maintenance_records", response_model=MaintenanceRecordRead, status_code=201)
def create_maintenance_record(payload: MaintenanceRecordCreate, db: Session = Depends(get_db)):
    obj = MaintenanceRecordService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/maintenance_records/{id_}", response_model=MaintenanceRecordRead)
def update_maintenance_record(id_: int, payload: MaintenanceRecordUpdate, db: Session = Depends(get_db)):
    obj = MaintenanceRecordService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/maintenance_records/{id_}", status_code=204)
def delete_maintenance_record(id_: int, db: Session = Depends(get_db)):
    if not MaintenanceRecordService(db).delete(id_): raise HTTPException(404)
    db.commit()

@router.post("/maintenance_records/{id_}/transition", response_model=MaintenanceRecordRead)
def transition_maintenance_record(id_: int, payload: dict, db: Session = Depends(get_db)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = MaintenanceRecordService(db).get(id_)
    if not obj:
        raise HTTPException(404)
    try:
        obj = MaintenanceRecordService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- Tag ---
@router.get("/tags", response_model=list[TagRead])
def list_tags(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return TagService(db).list(limit=limit, offset=offset)

@router.get("/tags/{id_}", response_model=TagRead)
def get_tag(id_: int, db: Session = Depends(get_db)):
    obj = TagService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/tags", response_model=TagRead, status_code=201)
def create_tag(payload: TagCreate, db: Session = Depends(get_db)):
    obj = TagService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/tags/{id_}", response_model=TagRead)
def update_tag(id_: int, payload: TagUpdate, db: Session = Depends(get_db)):
    obj = TagService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/tags/{id_}", status_code=204)
def delete_tag(id_: int, db: Session = Depends(get_db)):
    if not TagService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- link: Tool <-> Tag (tool_tags) ---
@router.post("/tools/{id_}/tags/{rid}", status_code=201)
def attach_tools_tags(id_: int, rid: int, db: Session = Depends(get_db)):
    ToolTagsLinks(db).attach(id_, rid); db.commit(); return {'linked': True}

@router.delete("/tools/{id_}/tags/{rid}", status_code=204)
def detach_tools_tags(id_: int, rid: int, db: Session = Depends(get_db)):
    ToolTagsLinks(db).detach(id_, rid); db.commit()

@router.get("/tools/{id_}/tags", response_model=list[TagRead])
def list_tools_tags(id_: int, db: Session = Depends(get_db)):
    return ToolTagsLinks(db).list_right(id_)
