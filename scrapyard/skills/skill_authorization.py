"""
skill_authorization — Enforce role-based access control for skill execution. Provides a centralized service to validate permissions against user roles.

### PART-META-JSON
{
  "name": "skill_authorization",
  "layer": "skills",
  "purpose": "Enforce role-based access control for skill execution. Provides a centralized service to validate permissions against user roles.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "skill_id (numeric string), user_role name; SQLAlchemy session with roles/permissions data.",
  "outputs": "authorize_skill_execution() -> bool; ORM models Role/Permission/Skill/SkillPermission.",
  "files_created": [],
  "security_notes": "Fail-closed: empty/malformed skill_id or role returns False. Authorization is only as trustworthy as the session's data - protect writes to the roles/permissions tables. Role table renamed skill_authorization_roles to resolve the shared-Base collision - do not rename back.",
  "ai_usage": "Import what you need from `scrapyard.skills.skill_authorization`.",
  "example": "from scrapyard.skills.skill_authorization import *",
  "import_path": "scrapyard.skills.skill_authorization"
}
### END-PART-META
"""
from sqlalchemy import String, Integer, Boolean, ForeignKey, Table, Column, select
from sqlalchemy.orm import Mapped, mapped_column, relationship, Session
from scrapyard.database.base_model import IntPKModel
from typing import List
import logging

logger = logging.getLogger(__name__)

# Define database tables
role_permissions_table = Table(
    'role_permissions', IntPKModel.metadata,
    Column('role_id', Integer, ForeignKey('skill_authorization_roles.id'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id'), primary_key=True)
)

class Role(IntPKModel):
    __tablename__ = 'skill_authorization_roles'
    
    name: Mapped[str] = mapped_column(String(50), unique=True)
    permissions: Mapped[List['Permission']] = relationship(
        secondary=role_permissions_table,
        back_populates='roles'
    )

class Permission(IntPKModel):
    __tablename__ = 'permissions'
    
    name: Mapped[str] = mapped_column(String(50), unique=True)
    roles: Mapped[List['Role']] = relationship(
        secondary=role_permissions_table,
        back_populates='permissions'
    )
    skills: Mapped[List['SkillPermission']] = relationship(
        back_populates='permission',
        overlaps="skills,skill_permissions"
    )

class SkillPermission(IntPKModel):
    __tablename__ = 'skill_permissions'
    
    skill_id: Mapped[int] = mapped_column(Integer, ForeignKey('skills.id'))
    permission_id: Mapped[int] = mapped_column(Integer, ForeignKey('permissions.id'))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    permission: Mapped['Permission'] = relationship(back_populates='skills')
    skill: Mapped['Skill'] = relationship(back_populates='permissions')

class Skill(IntPKModel):
    __tablename__ = 'skills'
    
    name: Mapped[str] = mapped_column(String(100), unique=True)
    permissions: Mapped[List['SkillPermission']] = relationship(
        back_populates='skill',
        overlaps="permissions,skill_permissions"
    )

class AuthorizationService:
    def __init__(self, session: Session):
        self.session = session
    
    def authorize_skill_execution(self, skill_id: str, user_role: str) -> bool:
        if not skill_id or not user_role:
            return False
        
        try:
            skill_id_int = int(skill_id)
        except (ValueError, TypeError):
            return False
        
        # Query to check if the role has the required permission for the given skill
        query = (
            select(SkillPermission)
            .join(Permission)
            .join(role_permissions_table, Permission.id == role_permissions_table.c.permission_id)
            .join(Role, role_permissions_table.c.role_id == Role.id)
            .where(
                SkillPermission.skill_id == skill_id_int,
                Role.name == user_role,
                SkillPermission.active == True
            )
        )
        
        result = self.session.execute(query).scalar_one_or_none()
        return result is not None

def _selftest():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, 'test.db')
        engine = create_engine(f'sqlite:///{db_path}')
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        
        # Initialize the database schema
        IntPKModel.metadata.create_all(engine)
        
        session = SessionLocal()
        try:
            # Add test data
            role1 = Role(name='admin')
            permission1 = Permission(name='execute_skill_1')
            skill1 = Skill(name='skill_1')
            
            session.add_all([role1, permission1, skill1])
            session.flush()  # Flush to assign IDs before creating association
            
            skill_permission1 = SkillPermission(skill_id=skill1.id, permission_id=permission1.id, active=True)
            session.add(skill_permission1)
            session.commit()
            
            # Test authorization
            auth_service = AuthorizationService(session)
            assert not auth_service.authorize_skill_execution('2', 'admin')  # Skill ID does not exist
            assert not auth_service.authorize_skill_execution('1', 'user')   # User has no permission for skill_1
            
            role1.permissions.append(permission1)  # Grant admin role the required permission
            session.commit()
            
            assert auth_service.authorize_skill_execution('1', 'admin')      # Admin can execute skill_1
            
            # Test edge cases
            assert not auth_service.authorize_skill_execution('', 'admin')   # Empty skill_id
            assert not auth_service.authorize_skill_execution('1', '')       # Empty role
            
        finally:
            session.close()

if __name__ == "__main__":
    _selftest()
