"""
crm_account_hierarchy — ** Manage hierarchical CRM account relationships, enabling tree traversal and structured parent/child link management. Supports complex account hierarchies for sales pipeline analytics and organizatio

### PART-META-JSON
{
  "name": "crm_account_hierarchy",
  "layer": "sales",
  "purpose": "Manage hierarchical CRM account relationships, enabling tree traversal and structured parent/child link management. Supports complex account hierarchies for sales pipeline analytics and organizatio.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_account_hierarchy(parent_id, child_id, session); get_account_tree(account_id, session); Account(...); AccountHierarchy(...).",
  "outputs": "Returns: create_account_hierarchy -> None; get_account_tree -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.sales.crm_account_hierarchy`.",
  "example": "from scrapyard.sales.crm_account_hierarchy import *",
  "import_path": "scrapyard.sales.crm_account_hierarchy"
}
### END-PART-META
"""
import logging
import os
import tempfile
from typing import Dict, Any, Set

from sqlalchemy import String, ForeignKey, select, UniqueConstraint, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session, sessionmaker
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class Account(IntPKModel):
    __tablename__ = "account"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class AccountHierarchy(IntPKModel):
    __tablename__ = "account_hierarchy"
    
    parent_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"), nullable=False)
    child_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"), nullable=False)
    
    __table_args__ = (
        UniqueConstraint("parent_id", "child_id", name="uq_account_hierarchy_parent_child"),
    )


def _get_ancestor_ids(account_id: int, session: Session) -> Set[int]:
    """Iteratively collect all ancestor IDs to avoid recursion depth issues."""
    ancestors: Set[int] = set()
    current_level = [account_id]
    
    while current_level:
        stmt = select(AccountHierarchy.parent_id).where(AccountHierarchy.child_id.in_(current_level))
        parents = session.execute(stmt).scalars().all()
        
        new_parents = [p for p in parents if p not in ancestors]
        if not new_parents:
            break
            
        ancestors.update(new_parents)
        current_level = new_parents
    
    return ancestors


def create_account_hierarchy(parent_id: int, child_id: int, session: Session) -> None:
    """Create a parent-child account relationship with cycle validation."""
    if parent_id == child_id:
        raise ValueError("Cannot create hierarchy: parent and child are the same")
    
    # Check for existing relationship
    existing = session.execute(
        select(AccountHierarchy).where(
            AccountHierarchy.parent_id == parent_id,
            AccountHierarchy.child_id == child_id
        )
    ).scalar_one_or_none()
    
    if existing:
        return
    
    # Cycle detection: if child is an ancestor of parent, creating this link forms a cycle
    ancestors = _get_ancestor_ids(parent_id, session)
    if child_id in ancestors:
        raise ValueError("Cycle detected in account hierarchy")
    
    hierarchy = AccountHierarchy(parent_id=parent_id, child_id=child_id)
    session.add(hierarchy)
    session.commit()


def get_account_tree(account_id: int, session: Session) -> Dict[str, Any]:
    """Recursively retrieve account hierarchy as a nested dictionary."""
    account = session.get(Account, account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found")
    
    # Get immediate children
    stmt = select(AccountHierarchy.child_id).where(AccountHierarchy.parent_id == account_id)
    child_ids = session.execute(stmt).scalars().all()
    
    # Recursively build children trees
    children = [get_account_tree(cid, session) for cid in child_ids]
    
    return {
        "id": account_id,
        "name": account.name,
        "children": children
    }


def _selftest():
    """Offline self-test using temporary SQLite database."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
        
        IntPKModel.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        
        session = SessionLocal()
        try:
            # Setup: Create accounts
            root = Account(name="Enterprise Corp")
            div1 = Account(name="Division A")
            div2 = Account(name="Division B")
            dept = Account(name="Department A1")
            standalone = Account(name="Standalone")
            
            session.add_all([root, div1, div2, dept, standalone])
            session.commit()
            
            rid, d1id, d2id, depid, sid = root.id, div1.id, div2.id, dept.id, standalone.id
            
            # Test: Create valid hierarchy (multi-level)
            create_account_hierarchy(rid, d1id, session)
            create_account_hierarchy(rid, d2id, session)
            create_account_hierarchy(d1id, depid, session)
            
            # Verify: Tree structure
            tree = get_account_tree(rid, session)
            assert tree["id"] == rid
            assert tree["name"] == "Enterprise Corp"
            assert len(tree["children"]) == 2
            
            # Find Division A and verify it has Department A1 as child
            div_a_node = next(n for n in tree["children"] if n["id"] == d1id)
            assert len(div_a_node["children"]) == 1
            assert div_a_node["children"][0]["id"] == depid
            assert div_a_node["children"][0]["children"] == []
            
            # Verify: Cycle detection (self-reference)
            try:
                create_account_hierarchy(rid, rid, session)
                assert False, "Expected ValueError for self-reference"
            except ValueError:
                pass
            
            # Verify: Cycle detection (indirect)
            # depid is under d1id which is under rid, so linking depid -> rid creates cycle
            try:
                create_account_hierarchy(depid, rid, session)
                assert False, "Expected ValueError for cycle"
            except ValueError as e:
                assert "cycle" in str(e).lower()
            
            # Verify: Idempotency (duplicate creation should not fail)
            create_account_hierarchy(rid, d1id, session)
            
            # Verify: Leaf node tree
            leaf_tree = get_account_tree(sid, session)
            assert leaf_tree["children"] == []
            
            # Verify: No orphaned relationships in database
            all_rels = session.execute(select(AccountHierarchy)).scalars().all()
            assert len(all_rels) == 3  # rid->d1id, rid->d2id, d1id->depid
            
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("crm_account_hierarchy selftest OK")
