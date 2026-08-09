"""
migrate.py — Apply/inspect schema migrations (Alembic) as the schema source of truth.

Usage:
  DATABASE_URL=... python tools/migrate.py upgrade [head]
  DATABASE_URL=... python tools/migrate.py downgrade <rev|base>
  DATABASE_URL=... python tools/migrate.py current
  DATABASE_URL=... python tools/migrate.py revision -m "msg" [--autogenerate]
  python tools/migrate.py check   # autogenerate dry-run; nonzero if the models have drifted from migrations
"""
from __future__ import annotations
try:
    import _bootstrap_path  # noqa: F401  (puts repo root on sys.path)
except ModuleNotFoundError:  # imported as tools.<mod>, not run as a script
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import _bootstrap_path  # noqa: F401
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg(script_location: str | None = None, url: str | None = None):
    from alembic.config import Config
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", script_location or os.path.join(ROOT, "migrations"))
    u = url or os.environ.get("DATABASE_URL")
    if u:
        cfg.set_main_option("sqlalchemy.url", u)
    return cfg


def check_drift(url: str | None = None) -> list:
    """Return the list of differences between the models and the migrated DB head.
    Empty list == migrations are the faithful source of truth."""
    from sqlalchemy import create_engine
    from alembic.migration import MigrationContext
    from alembic.autogenerate import compare_metadata
    from scrapyard.database.metadata import target_metadata
    eng = create_engine(url or os.environ["DATABASE_URL"])
    try:
        with eng.connect() as conn:
            mc = MigrationContext.configure(conn, opts={"compare_type": True})
            return list(compare_metadata(mc, target_metadata()))
    finally:
        eng.dispose()


def main(argv: list[str]) -> int:
    from alembic import command
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    cfg = _cfg()
    if cmd == "upgrade":
        command.upgrade(cfg, argv[1] if len(argv) > 1 else "head")
    elif cmd == "downgrade":
        command.downgrade(cfg, argv[1] if len(argv) > 1 else "-1")
    elif cmd == "current":
        command.current(cfg)
    elif cmd == "history":
        command.history(cfg)
    elif cmd == "revision":
        msg = argv[argv.index("-m") + 1] if "-m" in argv else "revision"
        command.revision(cfg, message=msg, autogenerate="--autogenerate" in argv)
    elif cmd == "check":
        diffs = check_drift()
        if diffs:
            print(f"DRIFT: {len(diffs)} difference(s) between models and migrations:")
            for d in diffs[:10]:
                print("  -", d)
            return 1
        print("OK: migrations match the models (no drift).")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
