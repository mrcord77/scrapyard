"""
backups — Scheduled DB + media backup scripts.

### PART-META-JSON
{
  "name": "backups",
  "layer": "deployment",
  "purpose": "Scheduled DB + media backup scripts.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: pg_dump_command(db_url, out); backup_plan(*, frequency, retention_days); configure_backup_policy(policy); run_scheduled_backup(policy); backup_media(media_root, output_dir); InvalidDatabaseURLException(...); MediaFileNotFoundException(...); BackupVerificationFailedError(...) (plus more).",
  "outputs": "Returns: pg_dump_command -> str; backup_plan -> dict; configure_backup_policy -> None; run_scheduled_backup -> BackupReport; backup_media -> List[MediaBackupItem].",
  "files_created": [],
  "security_notes": "Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps. Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import `pg_dump_command` from `scrapyard.deployment.backups` and call it as shown in `example`; run `py -m scrapyard.deployment.backups` to see its offline selftest.",
  "example": "from scrapyard.deployment.backups import pg_dump_command",
  "import_path": "scrapyard.deployment.backups"
}
### END-PART-META
"""
from __future__ import annotations
import hashlib
import os
import shutil
from datetime import datetime, timezone

STATUS = "core"

# Name of the checksum index file written inside every media backup directory.
_CHECKSUM_INDEX = "checksums.json"
_BACKUP_POLICY: Dict[str, Any] = {}
_BACKUP_EVENTS: List[Dict[str, Any]] = []


def _sha256_file(path: str) -> str:
    """Streaming SHA-256 of a file (constant memory, large-file safe)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def pg_dump_command(db_url: str, out: str) -> str:
    return f"pg_dump --no-owner --format=custom --file={out} {db_url}"
def backup_plan(*, frequency="daily", retention_days=30) -> dict:
    """Declarative backup policy other tooling/cron can consume."""
    return {"frequency": frequency, "retention_days": retention_days,
            "verify_restore": True, "offsite": True}

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

class InvalidDatabaseURLException(Exception):
    pass

class MediaFileNotFoundException(Exception):
    pass

class BackupVerificationFailedError(Exception):
    pass

class OffsiteUploadError(Exception):
    pass

class BackupPolicyValidationError(Exception):
    pass

class NoBackupsFoundError(Exception):
    pass

class MediaBackupItem(BaseModel):
    filename: str
    size: int
    checksum: str

class BackupReport(BaseModel):
    status: str
    timestamp: str
    backup_path: str
    media_backups: List[MediaBackupItem]

class VerificationReport(BaseModel):
    success: bool
    details: Optional[str] = None

class UploadResult(BaseModel):
    success: bool
    url: Optional[str] = None

class DeletionSummary(BaseModel):
    deleted_count: int
    audit_logs: List[str]

class RecoveryStatus(BaseModel):
    successful: bool
    message: str

def configure_backup_policy(policy: Any) -> None:
    values = dict(policy) if isinstance(policy, dict) else {
        name: getattr(policy, name) for name in (
            "frequency", "retention_days", "media_root", "output_dir",
            "offsite_target", "db_url") if hasattr(policy, name)
    }
    retention = values.get("retention_days", 30)
    if not isinstance(retention, int) or retention < 1:
        raise BackupPolicyValidationError("retention_days must be a positive integer")
    frequency = values.get("frequency", "daily")
    if frequency not in {"hourly", "daily", "weekly"}:
        raise BackupPolicyValidationError("frequency must be hourly, daily, or weekly")
    _BACKUP_POLICY.clear()
    _BACKUP_POLICY.update(values, retention_days=retention, frequency=frequency)

def run_scheduled_backup(policy: Any) -> BackupReport:
    backup_path = pg_dump_command(policy.db_url, "backup.dump")
    media_backups = backup_media(policy.media_root, "media_backup")

    try:
        verify_backup(backup_path, policy.db_url)
        upload_to_offsite(backup_path, "s3://bucket/backup.dump")
    except (BackupVerificationFailedError, OffsiteUploadError) as e:
        return BackupReport(status="failed", timestamp="now", backup_path=backup_path, media_backups=media_backups)

    return BackupReport(status="success", timestamp="now", backup_path=backup_path, media_backups=media_backups)

def backup_media(media_root: str, output_dir: str) -> List[MediaBackupItem]:
    """Copy every file under ``media_root`` into a fresh timestamped backup
    directory beneath ``output_dir``, recording each file's SHA-256 and size.

    Writes a ``checksums.json`` index inside the backup dir (consumed by
    verify_backup / recover_from_failure) and returns one MediaBackupItem per
    file. Raises MediaFileNotFoundException if the source directory is missing.
    """
    if not os.path.isdir(media_root):
        raise MediaFileNotFoundException(f"media_root not found: {media_root!r}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    dest = os.path.join(output_dir, f"media-{ts}")
    os.makedirs(dest, exist_ok=True)

    items: List[MediaBackupItem] = []
    index: Dict[str, Dict[str, Any]] = {}
    for root, _dirs, files in os.walk(media_root):
        for name in sorted(files):
            src = os.path.join(root, name)
            rel = os.path.relpath(src, media_root).replace(os.sep, "/")
            dst = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(dst) or dest, exist_ok=True)
            shutil.copy2(src, dst)
            checksum = _sha256_file(dst)
            size = os.path.getsize(dst)
            index[rel] = {"checksum": checksum, "size": size}
            items.append(MediaBackupItem(filename=rel, size=size, checksum=checksum))

    with open(os.path.join(dest, _CHECKSUM_INDEX), "w", encoding="utf-8") as f:
        json.dump({"created": ts, "backup_dir": dest, "files": index}, f, indent=2)
    return items


def verify_backup(backup_path: str, db_url: str | None = None) -> VerificationReport:
    """Verify a media backup directory by recomputing each file's SHA-256 and
    comparing it to the recorded checksum index. Returns a real pass/fail:
    success=False if the index is missing, a file is missing, or any checksum
    (or size) does not match. ``db_url`` is accepted for API compatibility but
    is not needed for checksum-based verification (a live pg_dump verify would
    require a running Postgres, which offline verification cannot assume)."""
    index_path = os.path.join(backup_path, _CHECKSUM_INDEX)
    if not os.path.isfile(index_path):
        return VerificationReport(success=False, details=f"no checksum index at {index_path!r}")
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            files = json.load(f).get("files", {})
    except (OSError, ValueError) as e:
        return VerificationReport(success=False, details=f"unreadable checksum index: {e}")

    if not files:
        return VerificationReport(success=False, details="checksum index lists no files")

    for rel, meta in files.items():
        path = os.path.join(backup_path, rel)
        if not os.path.isfile(path):
            return VerificationReport(success=False, details=f"missing file: {rel}")
        if os.path.getsize(path) != meta.get("size"):
            return VerificationReport(success=False, details=f"size mismatch: {rel}")
        if _sha256_file(path) != meta.get("checksum"):
            return VerificationReport(success=False, details=f"checksum mismatch: {rel}")
    return VerificationReport(success=True, details=f"{len(files)} file(s) verified")

def upload_to_offsite(backup_path: str, target: str) -> UploadResult:
    if not os.path.exists(backup_path):
        raise OffsiteUploadError(f"backup does not exist: {backup_path}")
    if target.startswith("file://"):
        target = target[7:]
    elif "://" in target:
        raise OffsiteUploadError(
            "remote upload requires a provider adapter; only local/file:// targets are built in"
        )
    destination = os.path.abspath(target)
    try:
        if os.path.isdir(backup_path):
            os.makedirs(destination, exist_ok=True)
            final = os.path.join(destination, os.path.basename(os.path.abspath(backup_path)))
            shutil.copytree(backup_path, final, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
            final = destination
            if os.path.isdir(destination):
                final = os.path.join(destination, os.path.basename(backup_path))
            shutil.copy2(backup_path, final)
    except OSError as exc:
        raise OffsiteUploadError(str(exc)) from exc
    return UploadResult(success=True, url=f"file://{os.path.abspath(final)}")

def delete_old_backups(policy: Any, base_dir: str) -> DeletionSummary:
    if not os.path.isdir(base_dir):
        raise NoBackupsFoundError(base_dir)
    retention = (policy.get("retention_days", 30) if isinstance(policy, dict)
                 else getattr(policy, "retention_days", 30))
    if retention < 1:
        raise BackupPolicyValidationError("retention_days must be positive")
    cutoff = datetime.now(timezone.utc).timestamp() - retention * 86400
    deleted, logs = 0, []
    for name in sorted(os.listdir(base_dir)):
        path = os.path.join(base_dir, name)
        if os.path.islink(path) or not os.path.isdir(path):
            continue
        if os.path.getmtime(path) < cutoff:
            shutil.rmtree(path)
            deleted += 1
            logs.append(f"deleted {name}")
    return DeletionSummary(deleted_count=deleted, audit_logs=logs)

def log_backup_event(event: Any) -> None:
    if isinstance(event, BackupEvent):
        payload = event.model_dump()
    elif isinstance(event, dict):
        payload = dict(event)
    else:
        payload = {"type": type(event).__name__, "details": {"value": str(event)}}
    payload["logged_at"] = datetime.now(timezone.utc).isoformat()
    _BACKUP_EVENTS.append(payload)

def recover_from_failure(backup_path: str, restore_dir: str) -> RecoveryStatus:
    """Restore a media backup: verify the source backup, copy every recorded file
    into ``restore_dir``, then re-verify the restored copies against the recorded
    checksums. Returns successful=False (without touching the destination) if the
    source backup does not itself verify, or if any restored file fails to match."""
    source = verify_backup(backup_path)
    if not source.success:
        return RecoveryStatus(successful=False, message=f"source backup invalid: {source.details}")

    with open(os.path.join(backup_path, _CHECKSUM_INDEX), "r", encoding="utf-8") as f:
        files = json.load(f).get("files", {})

    os.makedirs(restore_dir, exist_ok=True)
    for rel in files:
        src = os.path.join(backup_path, rel)
        dst = os.path.join(restore_dir, rel)
        os.makedirs(os.path.dirname(dst) or restore_dir, exist_ok=True)
        shutil.copy2(src, dst)

    for rel, meta in files.items():
        restored = os.path.join(restore_dir, rel)
        if not os.path.isfile(restored) or _sha256_file(restored) != meta.get("checksum"):
            return RecoveryStatus(successful=False, message=f"restore checksum mismatch: {rel}")
    return RecoveryStatus(successful=True, message=f"restored {len(files)} file(s) to {restore_dir}")

def serialize_backup_report(report: BackupReport) -> str:
    return json.dumps(report.model_dump())

def generate_backup_filename(policy: Any, timestamp: str) -> str:
    prefix = (policy.get("name", "backup") if isinstance(policy, dict)
              else getattr(policy, "name", "backup"))
    safe_prefix = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(prefix))
    safe_timestamp = "".join(c for c in str(timestamp) if c.isdigit())
    if not safe_timestamp:
        raise BackupPolicyValidationError("timestamp must contain digits")
    return f"{safe_prefix or 'backup'}-{safe_timestamp}.dump"

class BackupEvent(BaseModel):
    type: str
    details: Dict[str, Any]


def _selftest() -> None:
    # pg_dump command builder embeds format, output path and db url
    cmd = pg_dump_command("postgres://u:p@h/db", "/var/out.dump")
    assert cmd.startswith("pg_dump")
    assert "--format=custom" in cmd and "--file=/var/out.dump" in cmd
    assert "postgres://u:p@h/db" in cmd
    # declarative backup policy
    plan = backup_plan(frequency="hourly", retention_days=7)
    assert plan["frequency"] == "hourly" and plan["retention_days"] == 7
    assert plan["verify_restore"] is True and plan["offsite"] is True
    configure_backup_policy(plan)
    assert _BACKUP_POLICY["retention_days"] == 7
    assert generate_backup_filename({"name": "primary db"}, "2026-08-09T10:00:00Z") == \
        "primary-db-20260809100000.dump"
    try:
        configure_backup_policy({"retention_days": 0})
        raise AssertionError("accepted zero retention")
    except BackupPolicyValidationError:
        pass
    # report serialization round-trips through json
    rpt = BackupReport(
        status="success", timestamp="now", backup_path="/b",
        media_backups=[MediaBackupItem(filename="a.jpg", size=10, checksum="x")],
    )
    d = json.loads(serialize_backup_report(rpt))
    assert d["status"] == "success"
    assert d["media_backups"][0]["filename"] == "a.jpg"
    # NEGATIVE: pydantic rejects an un-coercible media size
    from pydantic import ValidationError
    try:
        MediaBackupItem(filename="a", size="not-an-int", checksum="x")
        raise AssertionError("invalid media item accepted")
    except ValidationError:
        pass

    # --- REAL create -> verify -> restore round-trip in a temp dir -------------
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        media_root = os.path.join(tmp, "media")
        os.makedirs(os.path.join(media_root, "sub"))
        with open(os.path.join(media_root, "a.txt"), "w", encoding="utf-8") as f:
            f.write("hello alpha")
        with open(os.path.join(media_root, "sub", "b.bin"), "wb") as f:
            f.write(b"\x00\x01\x02binary-payload\xff")

        out_dir = os.path.join(tmp, "backups")
        items = backup_media(media_root, out_dir)
        assert len(items) == 2, f"expected 2 media items, got {len(items)}"
        # A real backup directory was created and holds a checksum index.
        backup_dir = os.path.join(out_dir, os.listdir(out_dir)[0])
        assert os.path.isfile(os.path.join(backup_dir, _CHECKSUM_INDEX))
        # Checksums are the true SHA-256 of the source content (not a placeholder).
        expect = hashlib.sha256(b"hello alpha").hexdigest()
        assert any(it.filename == "a.txt" and it.checksum == expect for it in items), items

        # verify_backup on an intact backup passes.
        v = verify_backup(backup_dir)
        assert v.success, v
        offsite = os.path.join(tmp, "offsite")
        up = upload_to_offsite(backup_dir, offsite)
        assert up.success and os.path.isdir(up.url.removeprefix("file://"))
        log_backup_event(BackupEvent(type="success", details={"files": 2}))
        assert _BACKUP_EVENTS[-1]["type"] == "success"
        assert v.success is True, f"intact backup must verify: {v.details}"

        # restore round-trip reproduces the bytes exactly.
        restore_dir = os.path.join(tmp, "restored")
        rec = recover_from_failure(backup_dir, restore_dir)
        assert rec.successful is True, f"restore must succeed: {rec.message}"
        with open(os.path.join(restore_dir, "a.txt"), encoding="utf-8") as f:
            assert f.read() == "hello alpha", "restored content must match original"
        with open(os.path.join(restore_dir, "sub", "b.bin"), "rb") as f:
            assert f.read() == b"\x00\x01\x02binary-payload\xff"

        # NEGATIVE: tampering a backed-up file makes verification FAIL (this is
        # what would falsely pass on the old `pass`/None stub, which returned None
        # and never compared anything).
        with open(os.path.join(backup_dir, "a.txt"), "w", encoding="utf-8") as f:
            f.write("tampered")
        bad = verify_backup(backup_dir)
        assert bad.success is False, "tampered backup must fail verification"
        assert "a.txt" in (bad.details or ""), bad.details
        # ...and recovery from a corrupt backup refuses rather than restoring junk.
        bad_rec = recover_from_failure(backup_dir, os.path.join(tmp, "restored2"))
        assert bad_rec.successful is False, "recovery from corrupt backup must refuse"

        # NEGATIVE: verifying a directory with no checksum index is a clean fail.
        empty = os.path.join(tmp, "empty"); os.makedirs(empty)
        assert verify_backup(empty).success is False

        # NEGATIVE: backing up a missing source raises the typed exception.
        try:
            backup_media(os.path.join(tmp, "does-not-exist"), out_dir)
            raise AssertionError("missing media_root must raise")
        except MediaFileNotFoundException:
            pass

    print("backups selftest OK (pg_dump builder + real media backup/verify/restore "
          "round-trip incl. tamper and missing-source negatives)")


if __name__ == "__main__":
    _selftest()
