"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import UserCreate, UserUpdate, UserRead, MembershipCreate, MembershipUpdate, MembershipRead, PostCreate, PostUpdate, PostRead, SponsorCreate, SponsorUpdate, SponsorRead, MeetingCreate, MeetingUpdate, MeetingRead, AttendanceCreate, AttendanceUpdate, AttendanceRead, ChipCreate, ChipUpdate, ChipRead, JournalEntryCreate, JournalEntryUpdate, JournalEntryRead, MilestoneCreate, MilestoneUpdate, MilestoneRead
from .services import UserService, MembershipService, PostService, SponsorService, MeetingService, AttendanceService, ChipService, JournalEntryService, MilestoneService
from .models import Membership, Post, Attendance, Chip, JournalEntry, Milestone
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

# --- User ---
@router.get("/users", response_model=list[UserRead])
def list_users(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return UserService(db).list(limit=limit, offset=offset)

@router.get("/users/{id_}", response_model=UserRead)
def get_user(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = UserService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/users", response_model=UserRead, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = UserService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/users/{id_}", response_model=UserRead)
def update_user(id_: int, payload: UserUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = UserService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/users/{id_}", status_code=204)
def delete_user(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not UserService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Membership ---
@router.get("/memberships", response_model=list[MembershipRead])
def list_memberships(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Membership).where(Membership.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/memberships/{id_}", response_model=MembershipRead)
def get_membership(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MembershipService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/memberships", response_model=MembershipRead, status_code=201)
def create_membership(payload: MembershipCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = MembershipService(db).create(**data)
    _audit(db, action='membership.create', actor_user_id=uid, target=f'membership:{obj.id}')
    db.commit(); return obj

@router.put("/memberships/{id_}", response_model=MembershipRead)
def update_membership(id_: int, payload: MembershipUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MembershipService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = MembershipService(db).update(id_, **data)
    _audit(db, action='membership.update', actor_user_id=uid, target=f'membership:{id_}')
    db.commit(); return obj

@router.delete("/memberships/{id_}", status_code=204)
def delete_membership(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MembershipService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    MembershipService(db).delete(id_)
    _audit(db, action='membership.delete', actor_user_id=uid, target=f'membership:{id_}')
    db.commit()

# --- Post ---
@router.get("/posts", response_model=list[PostRead])
def list_posts(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Post).where(Post.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/posts/{id_}", response_model=PostRead)
def get_post(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = PostService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/posts", response_model=PostRead, status_code=201)
def create_post(payload: PostCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = PostService(db).create(**data)
    _audit(db, action='post.create', actor_user_id=uid, target=f'post:{obj.id}')
    db.commit(); return obj

@router.put("/posts/{id_}", response_model=PostRead)
def update_post(id_: int, payload: PostUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = PostService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = PostService(db).update(id_, **data)
    _audit(db, action='post.update', actor_user_id=uid, target=f'post:{id_}')
    db.commit(); return obj

@router.delete("/posts/{id_}", status_code=204)
def delete_post(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = PostService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    PostService(db).delete(id_)
    _audit(db, action='post.delete', actor_user_id=uid, target=f'post:{id_}')
    db.commit()

# --- Sponsor ---
@router.get("/sponsors", response_model=list[SponsorRead])
def list_sponsors(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return SponsorService(db).list(limit=limit, offset=offset)

@router.get("/sponsors/{id_}", response_model=SponsorRead)
def get_sponsor(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = SponsorService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/sponsors", response_model=SponsorRead, status_code=201)
def create_sponsor(payload: SponsorCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = SponsorService(db).create(**payload.model_dump(exclude_none=True))
    _audit(db, action='sponsor.create', actor_user_id=uid, target=f'sponsor:{obj.id}')
    db.commit(); return obj

@router.put("/sponsors/{id_}", response_model=SponsorRead)
def update_sponsor(id_: int, payload: SponsorUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = SponsorService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/sponsors/{id_}", status_code=204)
def delete_sponsor(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not SponsorService(db).get(id_): raise HTTPException(404)
    SponsorService(db).delete(id_)
    _audit(db, action='sponsor.delete', actor_user_id=uid, target=f'sponsor:{id_}')
    db.commit()

# --- Meeting ---
@router.get("/meetings", response_model=list[MeetingRead])
def list_meetings(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return MeetingService(db).list(limit=limit, offset=offset)

@router.get("/meetings/{id_}", response_model=MeetingRead)
def get_meeting(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MeetingService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/meetings", response_model=MeetingRead, status_code=201)
def create_meeting(payload: MeetingCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MeetingService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/meetings/{id_}", response_model=MeetingRead)
def update_meeting(id_: int, payload: MeetingUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MeetingService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/meetings/{id_}", status_code=204)
def delete_meeting(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not MeetingService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Attendance ---
@router.get("/attendances", response_model=list[AttendanceRead])
def list_attendances(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Attendance).where(Attendance.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/attendances/{id_}", response_model=AttendanceRead)
def get_attendance(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AttendanceService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/attendances", response_model=AttendanceRead, status_code=201)
def create_attendance(payload: AttendanceCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = AttendanceService(db).create(**data)
    _audit(db, action='attendance.create', actor_user_id=uid, target=f'attendance:{obj.id}')
    db.commit(); return obj

@router.put("/attendances/{id_}", response_model=AttendanceRead)
def update_attendance(id_: int, payload: AttendanceUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AttendanceService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = AttendanceService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/attendances/{id_}", status_code=204)
def delete_attendance(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = AttendanceService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    AttendanceService(db).delete(id_)
    _audit(db, action='attendance.delete', actor_user_id=uid, target=f'attendance:{id_}')
    db.commit()

# --- Chip ---
@router.get("/chips", response_model=list[ChipRead])
def list_chips(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Chip).where(Chip.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/chips/{id_}", response_model=ChipRead)
def get_chip(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ChipService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/chips", response_model=ChipRead, status_code=201)
def create_chip(payload: ChipCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = ChipService(db).create(**data)
    _audit(db, action='chip.create', actor_user_id=uid, target=f'chip:{obj.id}')
    db.commit(); return obj

@router.put("/chips/{id_}", response_model=ChipRead)
def update_chip(id_: int, payload: ChipUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ChipService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = ChipService(db).update(id_, **data)
    _audit(db, action='chip.update', actor_user_id=uid, target=f'chip:{id_}')
    db.commit(); return obj

@router.delete("/chips/{id_}", status_code=204)
def delete_chip(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ChipService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    ChipService(db).delete(id_)
    _audit(db, action='chip.delete', actor_user_id=uid, target=f'chip:{id_}')
    db.commit()

# --- JournalEntry ---
@router.get("/journal_entries", response_model=list[JournalEntryRead])
def list_journal_entries(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(JournalEntry).where(JournalEntry.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/journal_entries/{id_}", response_model=JournalEntryRead)
def get_journal_entry(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = JournalEntryService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/journal_entries", response_model=JournalEntryRead, status_code=201)
def create_journal_entry(payload: JournalEntryCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = JournalEntryService(db).create(**data)
    _audit(db, action='journal_entry.create', actor_user_id=uid, target=f'journal_entry:{obj.id}')
    db.commit(); return obj

@router.put("/journal_entries/{id_}", response_model=JournalEntryRead)
def update_journal_entry(id_: int, payload: JournalEntryUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = JournalEntryService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = JournalEntryService(db).update(id_, **data)
    db.commit(); return obj

@router.delete("/journal_entries/{id_}", status_code=204)
def delete_journal_entry(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = JournalEntryService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    JournalEntryService(db).delete(id_)
    _audit(db, action='journal_entry.delete', actor_user_id=uid, target=f'journal_entry:{id_}')
    db.commit()

# --- Milestone ---
@router.get("/milestones", response_model=list[MilestoneRead])
def list_milestones(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return db.scalars(select(Milestone).where(Milestone.user_id == uid).limit(limit).offset(offset)).all()

@router.get("/milestones/{id_}", response_model=MilestoneRead)
def get_milestone(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MilestoneService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    return obj

@router.post("/milestones", response_model=MilestoneRead, status_code=201)
def create_milestone(payload: MilestoneCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    data = payload.model_dump(exclude_none=True); data['user_id'] = uid  # force ownership
    obj = MilestoneService(db).create(**data)
    _audit(db, action='milestone.create', actor_user_id=uid, target=f'milestone:{obj.id}')
    db.commit(); return obj

@router.put("/milestones/{id_}", response_model=MilestoneRead)
def update_milestone(id_: int, payload: MilestoneUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MilestoneService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    data = payload.model_dump(exclude_unset=True); data.pop('user_id', None)  # owner is immutable
    obj = MilestoneService(db).update(id_, **data)
    _audit(db, action='milestone.update', actor_user_id=uid, target=f'milestone:{id_}')
    db.commit(); return obj

@router.delete("/milestones/{id_}", status_code=204)
def delete_milestone(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = MilestoneService(db).get(id_)
    if not obj or obj.user_id != uid:
        raise HTTPException(404)
    MilestoneService(db).delete(id_)
    _audit(db, action='milestone.delete', actor_user_id=uid, target=f'milestone:{id_}')
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
