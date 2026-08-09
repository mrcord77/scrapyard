"""
staff_records — Creates and updates staff profiles with validation.

### PART-META-JSON
{
  "name": "staff_records",
  "layer": "hr_lite_onboardi",
  "purpose": "Creates and updates staff profile records with field validation (required name/email, @-format check, whitelisted update fields). CANONICAL OWNER of the hr_lite_onboardi StaffProfile model (table staff_profiles): role_assignments and reporting_engine import StaffProfile from here.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model"],
  "inputs": "StaffData dataclass instances or partial-update dicts; an engine bound via configure().",
  "outputs": "Detached StaffProfile instances; ValueError on validation failures, RuntimeError when unconfigured.",
  "files_created": [],
  "security_notes": "Stores staff PII (names, emails, hire dates) in plaintext - restrict DB access and apply retention policy. Email validation is a minimal @-presence check, not RFC-compliant. No authorization checks: enforce who may create/update profiles in the calling layer.",
  "ai_usage": "Call configure(engine), then create_staff_profile/update_staff_profile; import StaffProfile as the canonical staff model.",
  "example": "from scrapyard.hr_lite_onboardi.staff_records import StaffProfile, create_staff_profile",
  "import_path": "scrapyard.hr_lite_onboardi.staff_records"
}
### END-PART-META
"""
from sqlalchemy import String, DateTime, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import tempfile
import os

# Module-level engine configuration
_engine: Optional[Any] = None


def configure(engine: Any) -> None:
    """Configure the module with a SQLAlchemy engine."""
    global _engine
    _engine = engine


@dataclass
class StaffData:
    """Type-safe data transfer object for staff profile creation."""
    full_name: str
    email: str
    department: Optional[str] = None
    position: Optional[str] = None
    hire_date: Optional[datetime] = None
    status: str = "onboarding"


class StaffProfile(IntPKModel):
    """ORM model for staff profiles with SQLAlchemy 2.x patterns."""
    __tablename__ = "staff_profiles"

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hire_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="onboarding")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )


def create_staff_profile(staff_data: StaffData) -> StaffProfile:
    """
    Create a new staff profile with validation and persistence.
    
    Args:
        staff_data: Validated StaffData instance
        
    Returns:
        StaffProfile: The created and persisted profile
        
    Raises:
        ValueError: If required fields are missing or invalid
        RuntimeError: If database engine is not configured
    """
    if _engine is None:
        raise RuntimeError("Database engine not configured. Call configure() first.")
    
    if not staff_data.full_name or not staff_data.full_name.strip():
        raise ValueError("full_name is required and cannot be empty")
    
    if not staff_data.email or not staff_data.email.strip():
        raise ValueError("email is required and cannot be empty")
    
    if "@" not in staff_data.email:
        raise ValueError("email must contain @ symbol")
    
    with Session(_engine) as session:
        profile = StaffProfile(
            full_name=staff_data.full_name.strip(),
            email=staff_data.email.strip(),
            department=staff_data.department,
            position=staff_data.position,
            hire_date=staff_data.hire_date,
            status=staff_data.status
        )
        session.add(profile)
        session.commit()
        session.refresh(profile)
        session.expunge(profile)
        return profile


def update_staff_profile(staff_id: int, data: Dict[str, Any]) -> StaffProfile:
    """
    Update an existing staff profile with partial data.
    
    Args:
        staff_id: The ID of the staff profile to update
        data: Dictionary of fields to update
        
    Returns:
        StaffProfile: The updated profile
        
    Raises:
        ValueError: If profile not found, data empty, or invalid fields provided
        RuntimeError: If database engine is not configured
    """
    if _engine is None:
        raise RuntimeError("Database engine not configured. Call configure() first.")
    
    if not data:
        raise ValueError("Update data cannot be empty")
    
    valid_fields = {'full_name', 'email', 'department', 'position', 'hire_date', 'status'}
    invalid_fields = set(data.keys()) - valid_fields
    if invalid_fields:
        raise ValueError(f"Invalid fields provided: {invalid_fields}")
    
    with Session(_engine) as session:
        stmt = select(StaffProfile).where(StaffProfile.id == staff_id)
        profile = session.execute(stmt).scalar_one_or_none()
        
        if profile is None:
            raise ValueError(f"Staff profile with id {staff_id} not found")
        
        for key, value in data.items():
            if key == 'email' and value and "@" not in str(value):
                raise ValueError("email must contain @ symbol")
            if key in ('full_name', 'email') and value and not str(value).strip():
                raise ValueError(f"{key} cannot be empty")
            setattr(profile, key, value)
        
        session.commit()
        session.refresh(profile)
        session.expunge(profile)
        return profile


def _selftest() -> None:
    """
    Offline self-test using temporary SQLite database.
    Verifies creation, update, querying, validation, and table structure.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_staff.db")
        engine = create_engine(f"sqlite:///{db_path}", future=True)
        
        try:
            # Configure module with test engine
            configure(engine)
            
            # Create tables
            IntPKModel.metadata.create_all(bind=engine)
            
            # Test 1: Create with valid data
            staff_data = StaffData(
                full_name="Alice Smith",
                email="alice.smith@company.com",
                department="Engineering",
                position="Software Engineer"
            )
            profile = create_staff_profile(staff_data)
            assert profile.id is not None, "Profile should have ID after creation"
            assert profile.full_name == "Alice Smith"
            assert profile.email == "alice.smith@company.com"
            assert profile.status == "onboarding"
            assert isinstance(profile.created_at, datetime)
            
            # Test 2: Query by ID using select()
            with Session(engine) as session:
                stmt = select(StaffProfile).where(StaffProfile.id == profile.id)
                fetched = session.execute(stmt).scalar_one()
                assert fetched.id == profile.id
                assert fetched.email == "alice.smith@company.com"
            
            # Test 3: Update with partial data
            update_data = {"department": "Research", "position": "Senior Engineer"}
            updated = update_staff_profile(profile.id, update_data)
            assert updated.department == "Research"
            assert updated.position == "Senior Engineer"
            assert updated.full_name == "Alice Smith"  # Unchanged
            assert updated.id == profile.id
            
            # Verify persistence of update
            with Session(engine) as session:
                stmt = select(StaffProfile).where(StaffProfile.id == profile.id)
                verify = session.execute(stmt).scalar_one()
                assert verify.department == "Research"
                assert verify.position == "Senior Engineer"
            
            # Test 4: Validation - empty full_name
            try:
                invalid_data = StaffData(full_name="", email="test@example.com")
                create_staff_profile(invalid_data)
                assert False, "Should raise ValueError for empty full_name"
            except ValueError as e:
                assert "full_name" in str(e)
            
            # Test 5: Validation - empty email
            try:
                invalid_data = StaffData(full_name="Test User", email="")
                create_staff_profile(invalid_data)
                assert False, "Should raise ValueError for empty email"
            except ValueError as e:
                assert "email" in str(e)
            
            # Test 6: Validation - invalid email format
            try:
                invalid_data = StaffData(full_name="Test User", email="notanemail")
                create_staff_profile(invalid_data)
                assert False, "Should raise ValueError for invalid email"
            except ValueError as e:
                assert "@" in str(e)
            
            # Test 7: Update non-existent ID
            try:
                update_staff_profile(99999, {"department": "HR"})
                assert False, "Should raise ValueError for non-existent ID"
            except ValueError as e:
                assert "not found" in str(e)
            
            # Test 8: Update with invalid field
            try:
                update_staff_profile(profile.id, {"invalid_field": "value"})
                assert False, "Should raise ValueError for invalid field"
            except ValueError as e:
                assert "Invalid fields" in str(e)
            
            # Test 9: Update with empty data
            try:
                update_staff_profile(profile.id, {})
                assert False, "Should raise ValueError for empty data"
            except ValueError as e:
                assert "empty" in str(e)
            
            # Test 10: Table structure verification
            with Session(engine) as session:
                # Verify table exists and has expected columns by querying
                from sqlalchemy import inspect
                inspector = inspect(engine)
                columns = {col['name'] for col in inspector.get_columns('staff_profiles')}
                expected_cols = {'id', 'full_name', 'email', 'department', 'position', 
                               'hire_date', 'status', 'created_at', 'updated_at'}
                assert expected_cols.issubset(columns), f"Missing columns: {expected_cols - columns}"
            
        finally:
            # Cleanup
            engine.dispose()
            configure(None)


if __name__ == "__main__":
    _selftest()
