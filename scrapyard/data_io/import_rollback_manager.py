"""
import_rollback_manager — Manages rollback of partially completed data imports to ensure data integrity on failure. Centralizes transaction state tracking and provides safe recovery mechanisms for import workflows.

### PART-META-JSON
{
  "name": "import_rollback_manager",
  "layer": "data_io",
  "purpose": "Manages rollback of partially completed data imports to ensure data integrity on failure. Centralizes transaction state tracking and provides safe recovery mechanisms for import workflows.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: ImportTransaction(...); ImportedRow(...); RollbackManager(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.data_io.import_rollback_manager`.",
  "example": "from scrapyard.data_io.import_rollback_manager import *",
  "import_path": "scrapyard.data_io.import_rollback_manager"
}
### END-PART-META
"""

from sqlalchemy import String, DateTime, Integer, func, select, delete, text, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
import re, os, logging, tempfile

logger = logging.getLogger(__name__)

# Table names come from our own import code, but we still validate them before
# interpolating into a DELETE (identifiers cannot be bound parameters).
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

@dataclass
class ImportTransaction(IntPKModel):
    __tablename__ = 'import_transaction'

    import_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default='PENDING')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_onupdate=func.now(),
        server_default=func.now()
    )

Index('import_transaction_import_id_idx', ImportTransaction.import_id)
UniqueConstraint(ImportTransaction.import_id, name='uq_import_transaction_import_id')


@dataclass
class ImportedRow(IntPKModel):
    """One row inserted under an import. Recording these is what makes rollback
    real: on failure we delete exactly the rows this import created."""
    __tablename__ = 'import_row'

    import_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_table: Mapped[str] = mapped_column(String(255), nullable=False)
    row_pk: Mapped[int] = mapped_column(Integer, nullable=False)

Index('import_row_import_id_idx', ImportedRow.import_id)


class RollbackManager:
    def __init__(self, session: Session):
        self.session = session

    def create_import_transaction(self, import_id: str) -> None:
        transaction = ImportTransaction(import_id=import_id)
        self.session.add(transaction)
        self.session.commit()

    def record_import(self, import_id: str, target_table: str, row_pk: int) -> None:
        """Register a row just inserted under this import so it can be undone.
        Call this for every row an import writes."""
        if not _IDENT_RE.match(target_table):
            raise ValueError(f"Unsafe target_table identifier: {target_table!r}")
        self.session.add(ImportedRow(import_id=import_id, target_table=target_table, row_pk=row_pk))
        self.session.commit()

    def rollback_import(self, import_id: str) -> None:
        transaction = self._get_transaction_by_import_id(import_id)
        if not transaction:
            logger.warning(f"No transaction found for import ID: {import_id}")
            return

        if transaction.status == 'COMPLETED':
            logger.info(f"Import already completed with ID: {import_id}. No rollback needed.")
            return

        self._revert_import_state(transaction)
        transaction.status = 'FAILED'
        self.session.commit()
        logger.warning(f"Rolled back import for ID: {import_id}")

    def _get_transaction_by_import_id(self, import_id: str) -> Optional[ImportTransaction]:
        query = select(ImportTransaction).where(ImportTransaction.import_id == import_id)
        result = self.session.execute(query).scalars().first()
        return result

    def _revert_import_state(self, transaction: ImportTransaction) -> None:
        """Actually undo the import: delete every recorded row, then drop the
        tracking rows. After this the previously-imported rows are gone."""
        import_id = transaction.import_id
        records = self.session.execute(
            select(ImportedRow).where(ImportedRow.import_id == import_id)
        ).scalars().all()
        if not records:
            logger.info(f"No recorded rows to revert for import ID: {import_id}")
            return

        # Group primary keys by target table so each table is cleared in one DELETE.
        by_table: dict[str, list[int]] = {}
        for rec in records:
            if not _IDENT_RE.match(rec.target_table):
                raise ValueError(f"Unsafe target_table identifier: {rec.target_table!r}")
            by_table.setdefault(rec.target_table, []).append(rec.row_pk)

        for table_name, pks in by_table.items():
            placeholders = ", ".join(f":pk{i}" for i in range(len(pks)))
            params = {f"pk{i}": pk for i, pk in enumerate(pks)}
            self.session.execute(
                text(f"DELETE FROM {table_name} WHERE id IN ({placeholders})"), params)
            logger.info(f"Reverted {len(pks)} row(s) from {table_name} for import {import_id}")

        # Clear the tracking rows for this import now that they are undone.
        self.session.execute(delete(ImportedRow).where(ImportedRow.import_id == import_id))
        self.session.flush()

def _selftest():
    from sqlalchemy.orm import sessionmaker, Mapped as _M, mapped_column as _mc
    from sqlalchemy import create_engine, String as _String
    from scrapyard.database.base_model import Base, IntPKModel as _IntPK

    # A realistic import target table living in the same metadata as the manager.
    class Widget(_IntPK):
        __tablename__ = 'widget'
        label: _M[str] = _mc(_String(255), nullable=False)

    def _widget_count(session) -> int:
        return session.execute(select(func.count()).select_from(Widget)).scalar_one()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'test.db')
        engine = create_engine(f'sqlite:///{db_path}')
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        with SessionLocal() as session:
            manager = RollbackManager(session)

            # --- Pre-existing rows that are NOT part of the failing import.
            for label in ('pre_a', 'pre_b'):
                session.add(Widget(label=label))
            session.commit()
            baseline = _widget_count(session)
            assert baseline == 2, f"baseline should be 2, got {baseline}"

            # --- A failing import: insert+record several rows, then blow up mid-way.
            import_id = 'batch_42'
            manager.create_import_transaction(import_id)
            rows_to_import = ['row_1', 'row_2', 'BOOM', 'row_4']
            try:
                for i, label in enumerate(rows_to_import):
                    if label == 'BOOM':
                        raise RuntimeError("simulated mid-import failure")
                    w = Widget(label=label)
                    session.add(w)
                    session.commit()            # row is now persisted
                    manager.record_import(import_id, 'widget', w.id)
            except RuntimeError:
                manager.rollback_import(import_id)

            # --- The whole point: the earlier imported rows must be GONE, not just
            #     a FAILED status. Row count returns exactly to the pre-import state.
            after = _widget_count(session)
            assert after == baseline, (
                f"rollback must remove imported rows: expected {baseline}, got {after}")

            # The pre-existing rows survived (rollback is scoped to the import).
            surviving = {r.label for r in session.execute(select(Widget)).scalars().all()}
            assert surviving == {'pre_a', 'pre_b'}, f"only imported rows should be gone: {surviving}"

            # Status is also FAILED, and tracking rows were cleared.
            txn = manager._get_transaction_by_import_id(import_id)
            assert txn.status == 'FAILED', "Transaction status should be 'FAILED'"
            remaining_tracked = session.execute(
                select(func.count()).select_from(ImportedRow)
                .where(ImportedRow.import_id == import_id)).scalar_one()
            assert remaining_tracked == 0, "tracking rows must be cleared after rollback"

    print("import_rollback_manager selftest passed")

if __name__ == "__main__":
    _selftest()
