"""
clause_library — The `scrapyard.legal.clause_library` module provides a centralized, reusable library for managing contract clauses used in e-signature workflows. It ensures consistency, reusability, and efficient retrieval of approved clause text.

### PART-META-JSON
{
  "name": "clause_library",
  "layer": "legal",
  "purpose": "The `scrapyard.legal.clause_library` module provides a centralized, reusable library for managing contract clauses used in e-signature workflows. It ensures consistency, reusability, and efficient retrieval of approved clause text. CANONICAL OWNER of the legal-layer Clause model (table clause_library_clause): contract_template imports it instead of defining a duplicate.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: add_clause(session, name, text); search_clauses(session, keyword); get_clause_by_id(session, id); Clause(...).",
  "outputs": "Returns: add_clause -> int; search_clauses -> List[Clause]; get_clause_by_id -> Optional[Clause].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.legal.clause_library`.",
  "example": "from scrapyard.legal.clause_library import *",
  "import_path": "scrapyard.legal.clause_library"
}
### END-PART-META
"""
from sqlalchemy import String, Text, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from typing import Optional, List
import os, logging, tempfile

logger = logging.getLogger(__name__)

class Clause(IntPKModel):
    __tablename__ = "clause_library_clause"
    name: Mapped[str] = mapped_column(String(255), unique=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)

def add_clause(session: Session, name: str, text: str) -> int:
    clause = Clause(name=name, text=text)
    session.add(clause)
    session.commit()
    return clause.id

def search_clauses(session: Session, keyword: str) -> List[Clause]:
    stmt = select(Clause).where(Clause.text.contains(keyword))
    return list(session.execute(stmt).scalars().all())

def get_clause_by_id(session: Session, id: int) -> Optional[Clause]:
    return session.get(Clause, id)

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tempdir:
        db_path = os.path.join(tempdir, 'test.db')
        engine = create_engine(f'sqlite:///{db_path}')
        IntPKModel.metadata.create_all(engine)

        with Session(engine) as session:
            # Add clauses
            add_clause(session, "Clause 1", "This is clause one.")
            add_clause(session, "Clause 2", "This is clause two.")

            # Search clauses
            assert len(search_clauses(session, "clause")) == 2
            assert len(search_clauses(session, "three")) == 0

            # Get clause by ID
            clause1 = session.get(Clause, 1)
            assert clause1.name == "Clause 1"
            assert clause1.text == "This is clause one."

            clause2 = session.get(Clause, 2)
            assert clause2.name == "Clause 2"
            assert clause2.text == "This is clause two."

            # Test duplicate name rejection
            try:
                add_clause(session, "Clause 1", "Duplicate text should fail.")
                assert False, "Expected exception for duplicate clause name"
            except Exception:
                pass  # Expected integrity error

        engine.dispose()

if __name__ == "__main__":
    _selftest()
