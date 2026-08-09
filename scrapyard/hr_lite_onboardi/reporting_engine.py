"""
reporting_engine — Generates persisted staff and role-usage reports from the canonical HR models.

### PART-META-JSON
{
  "name": "reporting_engine",
  "layer": "hr_lite_onboardi",
  "purpose": "Generates JSON staff reports (headcount, per-person profile with resolved role names) and role-usage reports (per-role assignment counts) as persisted Report rows. Owns only its Report model (table reporting_engine_reports); staff data comes from the canonical StaffProfile owned by scrapyard.hr_lite_onboardi.staff_records and role data from the canonical Role/RoleAssignment owned by scrapyard.hr_lite_onboardi.role_assignments.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model", "scrapyard.hr_lite_onboardi.staff_records", "scrapyard.hr_lite_onboardi.role_assignments"],
  "inputs": "An active SQLAlchemy Session over the shared HR schema.",
  "outputs": "Transient Report ORM instances whose content is a JSON document; caller decides whether to persist them.",
  "files_created": [],
  "security_notes": "Reports embed staff PII (names, emails, statuses) in plaintext JSON rows - restrict read access to reporting_engine_reports and apply retention limits. No authorization checks: enforce who may generate or read HR reports in the calling layer.",
  "ai_usage": "Pass a Session bound to the shared HR schema to generate_staff_report / generate_role_usage_report; persist the returned Report if needed.",
  "example": "from scrapyard.hr_lite_onboardi.reporting_engine import generate_staff_report",
  "import_path": "scrapyard.hr_lite_onboardi.reporting_engine"
}
### END-PART-META
"""
from sqlalchemy import Text, func, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel
import os
import json
import logging
import tempfile

# Canonical-owner pattern: staff_records owns StaffProfile; role_assignments
# owns Role and RoleAssignment. This part imports them instead of duplicates.
from scrapyard.hr_lite_onboardi.staff_records import StaffProfile
from scrapyard.hr_lite_onboardi.role_assignments import Role, RoleAssignment

logger = logging.getLogger(__name__)


class Report(IntPKModel):
    """Persisted report row (owned by reporting_engine)."""

    __tablename__ = "reporting_engine_reports"
    content: Mapped[str] = mapped_column(Text, nullable=False)


def generate_staff_report(session: Session) -> Report:
    """Build a staff report over the canonical StaffProfile rows.

    Each entry carries the profile fields plus the resolved role names from
    the canonical role-assignment tables.
    """
    staff_rows = session.execute(select(StaffProfile)).scalars().all()

    # Resolve role names per staff member in one query.
    role_map: dict = {}
    for staff_id, role_name in session.execute(
        select(RoleAssignment.staff_id, Role.name)
        .join(Role, RoleAssignment.role_id == Role.id)
    ):
        role_map.setdefault(staff_id, []).append(role_name)

    details = [
        {
            "id": s.id,
            "name": s.full_name,
            "email": s.email,
            "department": s.department,
            "position": s.position,
            "status": s.status,
            "roles": sorted(role_map.get(s.id, [])),
        }
        for s in staff_rows
    ]
    report_content = {"staff_count": len(staff_rows), "details": details}
    return Report(content=json.dumps(report_content))


def generate_role_usage_report(session: Session) -> Report:
    """Build a role-usage report: every role with its assignment count."""
    counts = dict(
        session.execute(
            select(RoleAssignment.role_id, func.count(RoleAssignment.id))
            .group_by(RoleAssignment.role_id)
        ).all()
    )
    roles = session.execute(select(Role)).scalars().all()
    details = [
        {**r.to_dict(), "assignment_count": int(counts.get(r.id, 0))}
        for r in roles
    ]
    report_content = {"role_count": len(roles), "details": details}
    return Report(content=json.dumps(report_content))


def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)

        IntPKModel.metadata.create_all(engine)

        SessionLocal = sessionmaker(bind=engine)

        with SessionLocal() as session:
            # Seed canonical staff and roles.
            staff1 = StaffProfile(full_name="John Doe", email="john.doe@example.com",
                                  department="Ops", status="active")
            staff2 = StaffProfile(full_name="Jane Smith", email="jane.smith@example.com",
                                  department="Eng", status="inactive")
            role1 = Role(name="Manager", description="Manages team")
            role2 = Role(name="Developer", description="Writes code")
            session.add_all([staff1, staff2, role1, role2])
            session.commit()

            session.add_all([
                RoleAssignment(staff_id=staff1.id, role_id=role1.id),
                RoleAssignment(staff_id=staff2.id, role_id=role2.id),
                RoleAssignment(staff_id=staff1.id, role_id=role2.id),
            ])
            session.commit()

            staff_report = generate_staff_report(session)
            assert isinstance(staff_report, Report)
            role_report = generate_role_usage_report(session)
            assert isinstance(role_report, Report)

            session.add_all([staff_report, role_report])
            session.commit()

            staff_id = staff_report.id
            role_id = role_report.id
            session.expire_all()

            retrieved_staff = session.get(Report, staff_id)
            assert retrieved_staff is not None
            retrieved_role = session.get(Report, role_id)
            assert retrieved_role is not None

            staff_content = json.loads(retrieved_staff.content)
            assert staff_content["staff_count"] == 2
            by_name = {d["name"]: d for d in staff_content["details"]}
            assert by_name["John Doe"]["roles"] == ["Developer", "Manager"]
            assert by_name["Jane Smith"]["roles"] == ["Developer"]
            assert by_name["Jane Smith"]["status"] == "inactive"

            role_content = json.loads(retrieved_role.content)
            assert role_content["role_count"] == 2
            usage = {d["name"]: d["assignment_count"] for d in role_content["details"]}
            assert usage == {"Manager": 1, "Developer": 2}

        engine.dispose()

    print("Self-test passed")


if __name__ == "__main__":
    _selftest()
