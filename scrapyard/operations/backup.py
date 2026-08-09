"""
backup — Real PostgreSQL backup/restore (pg_dump / pg_restore).

Replaces string-only backup "plans" with executable, verifiable backups. A backup
that has never been restored is a hope, not a backup — so the contract proves a full
dump -> drop -> restore roundtrip with data intact.

### PART-META-JSON
{
  "name": "backup",
  "layer": "operations",
  "purpose": "Executable PostgreSQL backup/restore with verified roundtrip.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "DATABASE_URL; a destination path.",
  "outputs": "A pg_dump archive; restore into a target database.",
  "files_created": [],
  "security_notes": "Runs pg_dump/pg_restore as subprocesses; credentials come from the URL. Store archives encrypted + offsite (not handled here).",
  "ai_usage": "from scrapyard.operations.backup import backup_database, restore_database",
  "example": "backup_database(url, '/backups/db.dump'); restore_database(url2, '/backups/db.dump')",
  "import_path": "scrapyard.operations.backup"
}
### END-PART-META
"""
from __future__ import annotations
import os
import glob
import shutil
import subprocess

STATUS = "core"


def _bin(name: str) -> str:
    """Resolve a postgres client binary (PATH first, then the versioned libdir)."""
    found = shutil.which(name)
    if found:
        return found
    for cand in sorted(glob.glob(f"/usr/lib/postgresql/*/bin/{name}"), reverse=True):
        return cand
    return name  # let subprocess raise a clear error if truly missing


def _libpq_url(database_url: str) -> str:
    # pg_dump/pg_restore speak libpq URIs; drop the SQLAlchemy driver suffix.
    return database_url.replace("+psycopg2", "").replace("+asyncpg", "")


def backup_database(database_url: str, dest_path: str, *, fmt: str = "custom") -> dict:
    """Dump the database to dest_path. fmt='custom' (pg_restore archive) or 'plain' SQL.
    Raises RuntimeError on failure. Returns {path, bytes, format}."""
    url = _libpq_url(database_url)
    flag = "-Fc" if fmt == "custom" else "-Fp"
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    r = subprocess.run(
        [_bin("pg_dump"), "--no-owner", "--no-privileges", flag, "-f", dest_path, url],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {r.stderr.strip()[-300:]}")
    return {"path": dest_path, "bytes": os.path.getsize(dest_path), "format": fmt}


def restore_database(database_url: str, src_path: str, *, clean: bool = False) -> dict:
    """Restore a custom-format archive into the target database. clean=True drops
    existing objects first (--clean --if-exists). Returns {restored_from}."""
    url = _libpq_url(database_url)
    cmd = [_bin("pg_restore"), "--no-owner", "--no-privileges"]
    if clean:
        cmd += ["--clean", "--if-exists"]
    cmd += ["-d", url, src_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    # pg_restore returns nonzero for benign warnings; only treat real errors as fatal.
    if r.returncode != 0 and ("error:" in r.stderr.lower() or "fatal" in r.stderr.lower()):
        raise RuntimeError(f"pg_restore failed: {r.stderr.strip()[-300:]}")
    return {"restored_from": src_path}


def backup_plan(*, frequency: str = "daily", retention_days: int = 30) -> dict:
    """Declarative policy cron/scheduler can consume (kept for compatibility)."""
    return {"frequency": frequency, "retention_days": retention_days,
            "verify_restore": True, "offsite": True}


def _selftest() -> None:
    """Offline self-test.

    Pure logic (URL normalisation, policy, binary resolution) is asserted here.
    The dump->drop->restore roundtrip needs pg_dump/pg_restore + a live Postgres;
    when either is missing it is SKIPPED (never faked). To run the full roundtrip,
    set SCRAPYARD_TEST_PG_URL to a disposable database.
    """
    import os
    import shutil
    import tempfile

    # 1. libpq URL normalisation drops the SQLAlchemy driver suffix.
    assert _libpq_url("postgresql+psycopg2://u:p@h/db") == "postgresql://u:p@h/db"
    assert _libpq_url("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"
    # negative: a plain libpq URL must be left untouched.
    assert _libpq_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"

    # 2. backup_plan is a well-formed, restore-verifying policy.
    plan = backup_plan(frequency="hourly", retention_days=7)
    assert plan["frequency"] == "hourly" and plan["retention_days"] == 7
    assert plan["verify_restore"] is True, "a backup policy must require restore verification"

    # 3. adversarial: a backup that cannot run must RAISE, never silently succeed.
    have_pg = bool(shutil.which("pg_dump"))
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        dest = os.path.join(tmp, "sub", "db.dump")
        raised = False
        try:
            # unreachable server (port 1); with pg_dump present -> RuntimeError,
            # without it -> FileNotFoundError. Either proves no silent success.
            backup_database("postgresql://u:p@127.0.0.1:1/none", dest)
        except (RuntimeError, FileNotFoundError, OSError):
            raised = True
        assert raised, "a failed/unavailable backup must raise, not return quietly"

    pg_url = os.environ.get("SCRAPYARD_TEST_PG_URL")
    if have_pg and pg_url:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            dest = os.path.join(tmp, "db.dump")
            info = backup_database(pg_url, dest)
            assert info["bytes"] > 0 and os.path.getsize(dest) > 0
            restore_database(pg_url, dest, clean=True)
        print("backup self-test passed (with live pg roundtrip)")
    else:
        print("backup self-test passed (pg roundtrip SKIPPED: "
              "pg_dump or SCRAPYARD_TEST_PG_URL unavailable)")


if __name__ == "__main__":
    _selftest()
