"""
audit_logs — Append-only admin action audit log.

### PART-META-JSON
{
  "name": "audit_logs",
  "layer": "admin",
  "purpose": "Tamper-evident append-only audit log (hash chain + hybrid post-quantum witness).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy",
    "cryptography",
    "dilithium-py"
  ],
  "inputs": "record(db, action=, actor_user_id=, target=, detail=); verify_chain(db, public=).",
  "outputs": "AuditLog rows carrying prev_hash/entry_hash/witness; verify_chain returns {ok, count, broken, witnessed}.",
  "files_created": [],
  "security_notes": "Tamper-EVIDENT, not tamper-proof: each entry chains to the prior entry's hash (detecting deletion/reordering) and carries a hybrid Ed25519+ML-DSA-65 witness over its content hash (detecting mutation and proving authenticity). Verify on read with verify_chain(). Set AUDIT_WITNESS_PUBLIC/SECRET (or use citadel custody) for durable cross-restart evidence; an auto-generated key is verifiable only within one process. Never log secrets/PII in detail. Append-only is enforced by convention here — pair with DB GRANTs/triggers for hard append-only at the storage layer.",
  "ai_usage": "record() to append; verify_chain() to audit integrity. Provide a stable witness keypair via env or citadel in production. Imported lazily so signing degrades gracefully if pq_signing is absent (chain still protects ordering/mutation).",
  "example": "from scrapyard.admin.audit_logs import record, verify_chain; record(db, action='delete_user', actor_user_id=1, target='user:7'); assert verify_chain(db)['ok']",
  "import_path": "scrapyard.admin.audit_logs"
}
### END-PART-META
"""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timezone

STATUS = "core"

from sqlalchemy import Integer, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from scrapyard.database.base_model import Base

_GENESIS = "0" * 64
_witness_cache: dict[str, bytes] = {}


class AuditLog(Base):
    """Append-only record of who did what to what, when — tamper-EVIDENT via a
    hash chain (detects deletion/reordering) plus a hybrid post-quantum witness
    signature (detects mutation and proves authenticity). Never updated/deleted."""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # tamper-evidence columns
    prev_hash: Mapped[str] = mapped_column(String(64), default=_GENESIS)
    entry_hash: Mapped[str] = mapped_column(String(64), default="")
    witness: Mapped[str] = mapped_column(Text, default="")  # hex hybrid signature over entry_hash


def _witness_keys():
    """Resolve the witness signing keypair. Production sets AUDIT_WITNESS_PUBLIC /
    AUDIT_WITNESS_SECRET (hex) or hands custody to citadel; absent that, a
    process-stable pair is generated so a single run is internally verifiable.
    A generated (non-persisted) key means the chain is verifiable within a run
    but not across restarts — set the env or use citadel for durable evidence."""
    pub_h, sec_h = os.environ.get("AUDIT_WITNESS_PUBLIC"), os.environ.get("AUDIT_WITNESS_SECRET")
    if pub_h and sec_h:
        return bytes.fromhex(pub_h), bytes.fromhex(sec_h)
    if "pub" not in _witness_cache:
        from scrapyard.security.pq_signing import generate_keypair
        pub, sec = generate_keypair()
        _witness_cache["pub"], _witness_cache["sec"] = pub, sec
    return _witness_cache["pub"], _witness_cache["sec"]


def _ts(dt: datetime) -> str:
    """Stable timestamp string for hashing that survives a DB round-trip.
    SQLite returns DateTime values naive even when written tz-aware, so normalize
    to naive-UTC microseconds on both the write and verify paths."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="microseconds")


def _entry_hash(actor_user_id, action, target, detail, created_at: datetime, prev_hash: str) -> str:
    payload = json.dumps({
        "actor_user_id": actor_user_id, "action": action, "target": target,
        "detail": detail, "created_at": _ts(created_at), "prev_hash": prev_hash,
    }, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def record(db, *, action: str, actor_user_id: int | None = None,
           target: str = "", detail: str = "") -> "AuditLog":
    """Append a tamper-evident audit entry. Chains to the prior entry's hash and
    attaches a hybrid post-quantum witness signature. Never logs secrets — the
    caller must keep `detail` clean."""
    from sqlalchemy import select
    prev = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).first()
    prev_hash = prev.entry_hash if (prev and prev.entry_hash) else _GENESIS
    created_at = datetime.now(timezone.utc)
    eh = _entry_hash(actor_user_id, action, target, detail, created_at, prev_hash)
    witness = ""
    try:
        from scrapyard.security.pq_signing import sign
        _pub, sec = _witness_keys()
        witness = sign(sec, eh.encode()).hex()
    except Exception:
        witness = ""  # signing unavailable -> chain still protects ordering/mutation
    entry = AuditLog(actor_user_id=actor_user_id, action=action, target=target,
                     detail=detail, created_at=created_at, prev_hash=prev_hash,
                     entry_hash=eh, witness=witness)
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db, public: bytes | None = None) -> dict:
    """Re-derive the whole chain and report tampering. Checks, per entry: the
    content hash still matches (no mutation), the prev_hash links to the prior
    entry (no deletion/reordering), and the witness signature verifies (authentic).
    Returns {ok, count, broken:[{id, reason}...], witnessed}."""
    from sqlalchemy import select
    from scrapyard.security.pq_signing import verify
    if public is None:
        public, _ = _witness_keys()
    rows = list(db.scalars(select(AuditLog).order_by(AuditLog.id)))
    broken, witnessed = [], 0
    expected_prev = _GENESIS
    for r in rows:
        eh = _entry_hash(r.actor_user_id, r.action, r.target, r.detail, r.created_at, r.prev_hash)
        if eh != r.entry_hash:
            broken.append({"id": r.id, "reason": "content mutated (hash mismatch)"})
        if r.prev_hash != expected_prev:
            broken.append({"id": r.id, "reason": "chain broken (deleted/reordered entry)"})
        if r.witness:
            witnessed += 1
            if not verify(public, r.entry_hash.encode(), bytes.fromhex(r.witness)):
                broken.append({"id": r.id, "reason": "witness signature invalid"})
        expected_prev = r.entry_hash
    return {"ok": not broken, "count": len(rows), "broken": broken, "witnessed": witnessed}


def for_target(db, target: str):
    """Read the audit trail for a target (admin-gated in the API layer)."""
    from sqlalchemy import select
    return list(db.scalars(select(AuditLog).where(AuditLog.target == target)
                           .order_by(AuditLog.created_at)))


def _selftest() -> None:
    """Offline self-test: chain integrity detects tampering."""
    import os
    import tempfile
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                e1 = record(db, action="one", actor_user_id=1, target="t:1", detail="a")
                e2 = record(db, action="two", actor_user_id=1, target="t:1", detail="b")
                e3 = record(db, action="three", actor_user_id=2, target="t:2")
                db.commit()
                assert e2.prev_hash == e1.entry_hash and e3.prev_hash == e2.entry_hash

                chain = verify_chain(db)
                assert chain["ok"] is True and chain["count"] == 3

                assert [a.action for a in for_target(db, "t:1")] == ["one", "two"]

                # Mutating an entry breaks verification.
                row = db.get(AuditLog, e2.id)
                row.detail = "tampered"
                db.commit()
                chain = verify_chain(db)
                assert chain["ok"] is False
                assert any(b["id"] == e2.id and "mutated" in b["reason"] for b in chain["broken"])
                row.detail = "b"
                db.commit()
                assert verify_chain(db)["ok"] is True

                # Deleting an entry breaks the chain.
                db.delete(db.get(AuditLog, e2.id))
                db.commit()
                chain = verify_chain(db)
                assert chain["ok"] is False
                assert any("chain broken" in b["reason"] for b in chain["broken"])
        finally:
            engine.dispose()
    print("audit_logs self-test passed")


if __name__ == "__main__":
    _selftest()
