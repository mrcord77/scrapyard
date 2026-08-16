"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import UserCreate, UserUpdate, UserRead, RepairTicketCreate, RepairTicketUpdate, RepairTicketRead
from .services import UserService, RepairTicketService
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

def require_role(role: str):
    """Dependency factory: authenticate, then 403 unless the user holds the role
    (or a superuser role). Used to gate write actions on role-managed entities."""
    def _dep(uid: int = Depends(current_user_id), db: Session = Depends(get_db)) -> int:
        from scrapyard.authorization.roles import has_role
        if not has_role(db, uid, role):
            raise HTTPException(403, f'requires role: {role}')
        return uid
    return _dep

router = APIRouter()

# --- User ---
@router.get("/users", response_model=list[UserRead])
def list_users(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    return UserService(db).list(limit=limit, offset=offset)

@router.get("/users/{id_}", response_model=UserRead)
def get_user(id_: int, db: Session = Depends(get_db)):
    obj = UserService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/users", response_model=UserRead, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    obj = UserService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/users/{id_}", response_model=UserRead)
def update_user(id_: int, payload: UserUpdate, db: Session = Depends(get_db)):
    obj = UserService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/users/{id_}", status_code=204)
def delete_user(id_: int, db: Session = Depends(get_db)):
    if not UserService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- RepairTicket ---
@router.get("/repair_tickets", response_model=list[RepairTicketRead])
def list_repair_tickets(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return RepairTicketService(db).list(limit=limit, offset=offset)

@router.get("/repair_tickets/{id_}", response_model=RepairTicketRead)
def get_repair_ticket(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = RepairTicketService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/repair_tickets", response_model=RepairTicketRead, status_code=201)
def create_repair_ticket(payload: RepairTicketCreate, db: Session = Depends(get_db), uid: int = Depends(require_role('admin'))):
    obj = RepairTicketService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/repair_tickets/{id_}", response_model=RepairTicketRead)
def update_repair_ticket(id_: int, payload: RepairTicketUpdate, db: Session = Depends(get_db), uid: int = Depends(require_role('admin'))):
    obj = RepairTicketService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/repair_tickets/{id_}", status_code=204)
def delete_repair_ticket(id_: int, db: Session = Depends(get_db), uid: int = Depends(require_role('admin'))):
    if not RepairTicketService(db).delete(id_): raise HTTPException(404)
    db.commit()

@router.post("/repair_tickets/{id_}/transition", response_model=RepairTicketRead)
def transition_repair_ticket(id_: int, payload: dict, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    to_state = payload.get('to')
    if not to_state:
        raise HTTPException(422, "missing target state 'to'")
    obj = RepairTicketService(db).get(id_)
    if not obj:
        raise HTTPException(404)
    try:
        obj = RepairTicketService(db).transition(id_, to_state)
    except WorkflowError as _e:
        raise HTTPException(409, str(_e))
    db.commit(); return obj

# --- role administration (admin-gated) ---
@router.post("/admin/roles/grant")
def admin_grant_role(payload: dict, uid: int = Depends(require_role('admin')), db: Session = Depends(get_db)):
    """Grant a role to a user. Requires the admin role (an owner/superuser also qualifies)."""
    target = payload.get('user_id'); role = payload.get('role')
    if not target or not role:
        raise HTTPException(422, 'user_id and role are required')
    from scrapyard.authorization.roles import grant as _grant, ROLE_PERMISSIONS
    if role not in ROLE_PERMISSIONS:
        raise HTTPException(422, f'unknown role: {role}')
    _grant(db, int(target), role)
    db.commit(); return {'granted': True, 'user_id': int(target), 'role': role}

@router.post("/admin/roles/revoke")
def admin_revoke_role(payload: dict, uid: int = Depends(require_role('admin')), db: Session = Depends(get_db)):
    """Revoke a role from a user. Requires the admin role."""
    target = payload.get('user_id'); role = payload.get('role')
    if not target or not role:
        raise HTTPException(422, 'user_id and role are required')
    from scrapyard.authorization.roles import revoke as _revoke
    _revoke(db, int(target), role)
    db.commit(); return {'revoked': True, 'user_id': int(target), 'role': role}

@router.get("/admin/roles/{user_id}")
def admin_list_roles(user_id: int, uid: int = Depends(require_role('admin')), db: Session = Depends(get_db)):
    """List the roles held by a user. Requires the admin role."""
    from scrapyard.authorization.roles import roles_for
    return {'user_id': user_id, 'roles': sorted(roles_for(db, user_id))}
