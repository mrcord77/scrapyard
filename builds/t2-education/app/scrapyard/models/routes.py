"""Generated FastAPI routers."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from .schemas import CourseCreate, CourseUpdate, CourseRead, ModuleCreate, ModuleUpdate, ModuleRead, LessonCreate, LessonUpdate, LessonRead, EnrollmentCreate, EnrollmentUpdate, EnrollmentRead, ProgressCreate, ProgressUpdate, ProgressRead
from .services import CourseService, ModuleService, LessonService, EnrollmentService, ProgressService
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

# --- Course ---
@router.get("/courses", response_model=list[CourseRead])
def list_courses(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return CourseService(db).list(limit=limit, offset=offset)

@router.get("/courses/{id_}", response_model=CourseRead)
def get_course(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CourseService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/courses", response_model=CourseRead, status_code=201)
def create_course(payload: CourseCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CourseService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/courses/{id_}", response_model=CourseRead)
def update_course(id_: int, payload: CourseUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = CourseService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/courses/{id_}", status_code=204)
def delete_course(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not CourseService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Module ---
@router.get("/modules", response_model=list[ModuleRead])
def list_modules(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return ModuleService(db).list(limit=limit, offset=offset)

@router.get("/modules/{id_}", response_model=ModuleRead)
def get_module(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ModuleService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/modules", response_model=ModuleRead, status_code=201)
def create_module(payload: ModuleCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ModuleService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/modules/{id_}", response_model=ModuleRead)
def update_module(id_: int, payload: ModuleUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ModuleService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/modules/{id_}", status_code=204)
def delete_module(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not ModuleService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Lesson ---
@router.get("/lessons", response_model=list[LessonRead])
def list_lessons(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return LessonService(db).list(limit=limit, offset=offset)

@router.get("/lessons/{id_}", response_model=LessonRead)
def get_lesson(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LessonService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/lessons", response_model=LessonRead, status_code=201)
def create_lesson(payload: LessonCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LessonService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/lessons/{id_}", response_model=LessonRead)
def update_lesson(id_: int, payload: LessonUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = LessonService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/lessons/{id_}", status_code=204)
def delete_lesson(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not LessonService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Enrollment ---
@router.get("/enrollments", response_model=list[EnrollmentRead])
def list_enrollments(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return EnrollmentService(db).list(limit=limit, offset=offset)

@router.get("/enrollments/{id_}", response_model=EnrollmentRead)
def get_enrollment(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EnrollmentService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/enrollments", response_model=EnrollmentRead, status_code=201)
def create_enrollment(payload: EnrollmentCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EnrollmentService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/enrollments/{id_}", response_model=EnrollmentRead)
def update_enrollment(id_: int, payload: EnrollmentUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = EnrollmentService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/enrollments/{id_}", status_code=204)
def delete_enrollment(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not EnrollmentService(db).delete(id_): raise HTTPException(404)
    db.commit()

# --- Progress ---
@router.get("/progresses", response_model=list[ProgressRead])
def list_progresses(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    return ProgressService(db).list(limit=limit, offset=offset)

@router.get("/progresses/{id_}", response_model=ProgressRead)
def get_progress(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProgressService(db).get(id_)
    if not obj: raise HTTPException(404)
    return obj

@router.post("/progresses", response_model=ProgressRead, status_code=201)
def create_progress(payload: ProgressCreate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProgressService(db).create(**payload.model_dump(exclude_none=True))
    db.commit(); return obj

@router.put("/progresses/{id_}", response_model=ProgressRead)
def update_progress(id_: int, payload: ProgressUpdate, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    obj = ProgressService(db).update(id_, **payload.model_dump(exclude_unset=True))
    if not obj: raise HTTPException(404)
    db.commit(); return obj

@router.delete("/progresses/{id_}", status_code=204)
def delete_progress(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):
    if not ProgressService(db).delete(id_): raise HTTPException(404)
    db.commit()
