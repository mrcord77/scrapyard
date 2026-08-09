"""
role_assignments — Assigns and removes staff roles with duplicate protection.

### PART-META-JSON
{
  "name": "role_assignments",
  "layer": "hr_lite_onboardi",
  "purpose": "Assigns roles to staff members and removes them, with a unique constraint preventing duplicate assignments. CANONICAL OWNER of the hr_lite_onboardi Role model (table role_assignments_roles): access_control and reporting_engine import Role from here. Staff rows live in the canonical StaffProfile model owned by scrapyard.hr_lite_onboardi.staff_records.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model", "scrapyard.hr_lite_onboardi.staff_records"],
  "inputs": "staff_id and role_id integers; an engine bound via configure_engine() (or set by _selftest).",
  "outputs": "Persisted RoleAssignment rows; IntegrityError on duplicate assignment; silent no-op removal of missing assignments.",
  "files_created": [],
  "security_notes": "No authorization checks: any caller can grant or strip any role, so restrict who may call assign_role/remove_role in the calling layer (role changes are privilege escalation primitives). SQLite does not enforce the staff/role foreign keys unless PRAGMA foreign_keys=ON; validate referenced ids exist when running on SQLite.",
  "ai_usage": "Call configure_engine(engine), then assign_role/remove_role; import Role as the canonical roles model.",
  "example": "from scrapyard.hr_lite_onboardi.role_assignments import Role, assign_role",
  "import_path": "scrapyard.hr_lite_onboardi.role_assignments"
}
### END-PART-META
"""
from sqlalchemy import ForeignKey, UniqueConstraint, create_engine, select, String, Text
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from sqlalchemy.exc import IntegrityError
from typing import Optional
import logging

# Canonical-owner pattern: staff_records owns the StaffProfile model.
from scrapyard.hr_lite_onboardi.staff_records import StaffProfile

logger = logging.getLogger(__name__)

_engine = None


def configure_engine(engine) -> None:
    """Bind this module to a SQLAlchemy engine."""
    global _engine
    _engine = engine


class Role(IntPKModel):
    """Canonical hr_lite_onboardi role model (owned by role_assignments)."""

    __tablename__ = "role_assignments_roles"
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description}


class RoleAssignment(IntPKModel):
    __tablename__ = "role_assignments"
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_profiles.id"))
    role_id: Mapped[int] = mapped_column(ForeignKey("role_assignments_roles.id"))
    __table_args__ = (UniqueConstraint('staff_id', 'role_id', name='uq_staff_role'),)


def assign_role(staff_id: int, role_id: int) -> None:
    """Assign a role to a staff member. Raises IntegrityError if duplicate."""
    if _engine is None:
        raise RuntimeError("Database engine not configured")
    with Session(_engine) as session:
        assignment = RoleAssignment(staff_id=staff_id, role_id=role_id)
        session.add(assignment)
        session.commit()


def remove_role(staff_id: int, role_id: int) -> None:
    """Remove a role assignment from a staff member."""
    if _engine is None:
        raise RuntimeError("Database engine not configured")
    with Session(_engine) as session:
        stmt = select(RoleAssignment).where(
            RoleAssignment.staff_id == staff_id,
            RoleAssignment.role_id == role_id
        )
        assignment = session.execute(stmt).scalar_one_or_none()
        if assignment:
            session.delete(assignment)
            session.commit()


def _selftest():
    import tempfile
    import os

    global _engine

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        _engine = create_engine(f"sqlite:///{db_path}", echo=False)

        # Create all tables including canonical staff/role dependencies
        IntPKModel.metadata.create_all(_engine)

        try:
            # Seed canonical staff and role rows so FK targets really exist.
            with Session(_engine) as session:
                staff = StaffProfile(full_name="Test Person", email="test.person@example.com")
                role = Role(name="Onboarding Buddy", description="Helps new hires")
                session.add_all([staff, role])
                session.commit()
                staff_id, role_id = staff.id, role.id

            # Test assign_role
            assign_role(staff_id, role_id)

            with Session(_engine) as session:
                stmt = select(RoleAssignment)
                rows = session.execute(stmt).scalars().all()
                assert len(rows) == 1, f"Expected 1 assignment, got {len(rows)}"
                assert rows[0].staff_id == staff_id
                assert rows[0].role_id == role_id

            # Test duplicate assignment prevention
            try:
                assign_role(staff_id, role_id)
                assert False, "Duplicate role assignment should not be allowed"
            except IntegrityError:
                pass

            # Test remove_role
            remove_role(staff_id, role_id)

            with Session(_engine) as session:
                count = len(session.execute(select(RoleAssignment)).scalars().all())
                assert count == 0, f"Expected 0 assignments after removal, got {count}"

            # Test idempotent remove (should not raise)
            remove_role(staff_id, role_id)

        finally:
            _engine.dispose()
            _engine = None

    print("Self-test passed")


if __name__ == "__main__":
    _selftest()
