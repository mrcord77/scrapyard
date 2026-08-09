"""
state_tracker — Tracks the state of an agent throughout its operations, providing a persistent and auditable history of state transitions.

### PART-META-JSON
{
  "name": "state_tracker",
  "layer": "agents",
  "purpose": "Tracks the state of an agent throughout its operations, providing a persistent and auditable history of state transitions.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: StateTracker(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.agents.state_tracker`.",
  "example": "from scrapyard.agents.state_tracker import *",
  "import_path": "scrapyard.agents.state_tracker"
}
### END-PART-META
"""

from sqlalchemy import DateTime, JSON, select, create_engine
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import os, logging, tempfile

logger = logging.getLogger(__name__)

class StateTracker(IntPKModel):
    __tablename__ = 'states'
    
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )
    data: Mapped[Dict[str, Any]] = mapped_column(JSON)

    @classmethod
    def update_state(cls, new_state: Dict[str, Any], session: Session) -> None:
        state_entry = cls(data=new_state)
        session.add(state_entry)
        session.commit()

    @classmethod
    def get_state(cls, session: Session) -> Optional[Dict[str, Any]]:
        latest_state = session.execute(
            select(cls).order_by(cls.timestamp.desc()).limit(1)
        ).scalar_one_or_none()
        if latest_state:
            return latest_state.data
        return None

def _selftest() -> bool:
    """Offline self-test for the state-history tracker.

    NOTE (deviation): this part is a persistent, append-only state *history*, not a
    state *machine* with a legal-transition table, so there is no "illegal
    transition" to reject. The adversarial case exercised here is instead the
    empty-history read (must return None, not crash) and the ordering guarantee
    that ``get_state`` returns the LATEST write and never a stale earlier one.
    """
    import time

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'state_tracker_test.db')

        engine = create_engine(f"sqlite:///{db_path}")
        StateTracker.metadata.create_all(engine)

        with Session(engine) as session:
            # Adversarial/negative: reading before any state exists returns None
            # rather than raising.
            assert StateTracker.get_state(session) is None, "empty history must read as None"

            # A write is retrievable.
            StateTracker.update_state({'phase': 'init', 'n': 1}, session)
            assert StateTracker.get_state(session) == {'phase': 'init', 'n': 1}

            # A later write supersedes the earlier one (latest-wins ordering).
            time.sleep(0.01)  # ensure a strictly later timestamp on coarse clocks
            StateTracker.update_state({'phase': 'running', 'n': 2}, session)
            latest = StateTracker.get_state(session)
            assert latest == {'phase': 'running', 'n': 2}, f"expected latest state, got {latest}"
            assert latest['phase'] != 'init', "get_state must not return the stale earlier state"

            # History is append-only: both rows persist even though get_state shows one.
            from sqlalchemy import func
            count = session.execute(select(func.count()).select_from(StateTracker)).scalar()
            assert count == 2, f"expected 2 history rows, got {count}"

        engine.dispose()

    print("state_tracker selftest: PASS")
    return True

if __name__ == "__main__":
    if not _selftest():
        raise Exception("Self-test failed")
