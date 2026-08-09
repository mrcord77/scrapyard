"""
funnels — Define + compute conversion funnels.

### PART-META-JSON
{
  "name": "funnels",
  "layer": "analytics",
  "purpose": "Define + compute conversion funnels.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: funnel(db, steps).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `funnel` from `scrapyard.analytics.funnels` and call it as shown in `example`; run `py -m scrapyard.analytics.funnels` to see its offline selftest.",
  "example": "from scrapyard.analytics.funnels import funnel",
  "import_path": "scrapyard.analytics.funnels"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
def funnel(db, steps: list[str]):
    """Count users who reached each step in order; conversion = step/first."""
    from scrapyard.analytics.event_tracking import count_events
    counts=[(s, count_events(db, s)) for s in steps]
    first=counts[0][1] if counts and counts[0][1] else 0
    return [{"step":s,"count":c,"conversion":round(c/first,3) if first else 0.0} for s,c in counts]


def _selftest() -> None:
    import tempfile, os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scrapyard.database.base_model import IntPKModel
    from scrapyard.analytics.event_tracking import track_event

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        IntPKModel.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                for uid in (1, 2, 3, 4):
                    track_event(db, "visit", user_id=uid)
                for uid in (1, 2):
                    track_event(db, "signup", user_id=uid)
                track_event(db, "purchase", user_id=1)
                db.commit()

                result = funnel(db, ["visit", "signup", "purchase"])
                assert [r["count"] for r in result] == [4, 2, 1]
                assert [r["conversion"] for r in result] == [1.0, 0.5, 0.25]

                # empty funnel and zero-first funnel degrade gracefully
                assert funnel(db, []) == []
                zero = funnel(db, ["never_happened", "visit"])
                assert zero[0]["conversion"] == 0.0
        finally:
            engine.dispose()


if __name__ == "__main__":
    _selftest()
    print("funnels selftest OK")
