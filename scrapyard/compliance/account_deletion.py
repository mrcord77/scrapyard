"""
account_deletion — Hard/soft delete + downstream purge with a deletion registry, hooks, and GDPR serialization.

### PART-META-JSON
{
  "name": "account_deletion",
  "layer": "compliance",
  "purpose": "Account deletion for GDPR erasure: soft delete into a registry table (account_deletion_deleted_accounts), hard-delete cascade across every mapped table with a user_id column, bulk deletion under a policy, aged purge of soft-deleted records with real counts, JSON serialization of results and full-account GDPR export, plus working audit/metrics hook registries and deletion events.",
  "addition": false,
  "status": "core",
  "dependencies": ["sqlalchemy"],
  "inputs": "SQLAlchemy Session, user ids, SoftDeletePolicy, DeletionFilter expressions ('column op literal'), hook callables.",
  "outputs": "Per-table deletion counts, registry listings, purge summaries, JSON-safe dicts; UserNotFoundError/InvalidFilterError/etc on bad input.",
  "files_created": [],
  "security_notes": "DESTRUCTIVE-BY-CONFIRMATION: delete_account and purge_deleted_records hard-delete rows across all mapped tables with a user_id column. The hard-delete cascade is fail-safe by default - delete_account(confirm=False) performs a dry run (counts only, no rows removed) and only confirm=True with dry_run=False actually deletes; dry_run=True always wins over confirm. gdpr_dsr passes confirm=True because a data-subject erasure request IS the explicit confirmation. Filter expressions are parsed structurally (column, operator, literal) and compared in Python - never eval()'d. Hooks run in-process: a raising hook is logged and counted, never allowed to abort a deletion mid-cascade. No authorization checks: restrict who may call these functions in the calling layer, and audit every call (delete_account writes to the admin audit log itself).",
  "ai_usage": "Import deletion functions from `scrapyard.compliance.account_deletion`; call delete_account(db, uid, confirm=True) for real erasure, soft_delete_account for reversible removal, purge_deleted_records for aged cleanup.",
  "example": "from scrapyard.compliance.account_deletion import delete_account, soft_delete_account, list_deleted_accounts",
  "import_path": "scrapyard.compliance.account_deletion"
}
### END-PART-META
"""
from __future__ import annotations

import json
import logging
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta, timezone, date

from sqlalchemy import inspect, delete, select, String, Boolean, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

STATUS = "core"

logger = logging.getLogger(__name__)


class SoftDeletePolicy:
    def __init__(self, enable_soft_delete: bool = True, soft_delete_column: str = 'is_deleted'):
        if not isinstance(enable_soft_delete, bool):
            raise InvalidPolicyError("enable_soft_delete must be a boolean")
        if not isinstance(soft_delete_column, str) or not soft_delete_column:
            raise InvalidPolicyError("soft_delete_column must be a non-empty string")
        self.enable_soft_delete = enable_soft_delete
        self.soft_delete_column = soft_delete_column


class UserNotFoundError(Exception):
    pass


class InvalidPolicyError(Exception):
    pass


class InvalidFilterError(Exception):
    pass


class BulkDeleteLimitExceeded(Exception):
    pass


class AuditHookError(Exception):
    pass


class MetricsHookError(Exception):
    pass


class CascadeConfigError(Exception):
    pass


class PurgeLimitExceeded(Exception):
    pass


class SerializationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Deletion registry model
# ---------------------------------------------------------------------------

class DeletionRecord(IntPKModel):
    """Soft-delete registry row: one entry per deleted (or purge-pending) account."""

    __tablename__ = "account_deletion_deleted_accounts"

    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="soft")
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc))
    purged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    purged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Safe deletion filters (no eval)
# ---------------------------------------------------------------------------

_FILTER_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">=": lambda a, b: a is not None and a >= b,
    "<=": lambda a, b: a is not None and a <= b,
    ">": lambda a, b: a is not None and a > b,
    "<": lambda a, b: a is not None and a < b,
}


class DeletionFilter:
    """Structural filter: ``column op literal`` compared in Python, never eval()'d.

    Supported operators: == != >= <= > <.
    Supported literals: true/false/null, integers, floats, 'quoted' / "quoted" strings.
    """

    def __init__(self, expr: str):
        if not expr or not isinstance(expr, str):
            raise InvalidFilterError("Filter expression must be a non-empty string")
        self.expr = expr
        parts = None
        for op in ("==", "!=", ">=", "<=", ">", "<"):
            if op in expr:
                left, _, right = expr.partition(op)
                parts = (left.strip(), op, right.strip())
                break
        if parts is None or not parts[0] or not parts[2]:
            raise InvalidFilterError(f"Cannot parse filter expression: {expr!r}")
        self.column, self.op, self.value = parts[0], parts[1], self._parse_literal(parts[2])

    @staticmethod
    def _parse_literal(raw: str) -> Any:
        low = raw.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        if low in ("null", "none"):
            return None
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
            return raw[1:-1]
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            raise InvalidFilterError(f"Unsupported literal in filter: {raw!r}")

    def matches(self, obj: Any) -> bool:
        if not hasattr(obj, self.column):
            raise InvalidFilterError(
                f"Filter column {self.column!r} does not exist on {type(obj).__name__}")
        return bool(_FILTER_OPS[self.op](getattr(obj, self.column), self.value))


# ---------------------------------------------------------------------------
# Hook registries (working: registered hooks actually fire)
# ---------------------------------------------------------------------------

_audit_hooks: List[Callable[[str, str, str, dict], None]] = []
_metrics_hooks: List[Callable[[str, int, dict], None]] = []
_cascade_tables: Optional[List[str]] = None


def register_audit_hook(hook: Callable[[str, str, str, dict], None]) -> Callable[[], None]:
    """Register an audit hook fired on every deletion event. Returns an unregister callable."""
    if not callable(hook):
        raise AuditHookError("Hook must be a callable")
    _audit_hooks.append(hook)

    def _unregister() -> None:
        if hook in _audit_hooks:
            _audit_hooks.remove(hook)
    return _unregister


def register_metrics_hook(hook: Callable[[str, int, dict], None]) -> Callable[[], None]:
    """Register a metrics hook fired with (metric, value, tags). Returns an unregister callable."""
    if not callable(hook):
        raise MetricsHookError("Hook must be a callable")
    _metrics_hooks.append(hook)

    def _unregister() -> None:
        if hook in _metrics_hooks:
            _metrics_hooks.remove(hook)
    return _unregister


def emit_deletion_event(event_type: str, payload: Dict[str, Any]) -> int:
    """Fire all registered audit hooks with this event.

    Returns the number of hooks that ran successfully. A raising hook is
    logged and counted as failed, never allowed to abort the caller.
    """
    if not event_type or not isinstance(event_type, str):
        raise ValueError("event_type must be a non-empty string")
    if not isinstance(payload, dict) or not payload:
        raise ValueError("payload must be a non-empty dictionary")
    ok = 0
    target = str(payload.get("target", payload.get("user_id", "")))
    for hook in list(_audit_hooks):
        try:
            hook(event_type, target, "emitted", payload)
            ok += 1
        except Exception:  # noqa: BLE001 - hook faults must not abort deletions
            logger.exception("audit hook %r failed for event %s", hook, event_type)
    return ok


def _emit_metric(metric: str, value: int, tags: Dict[str, Any]) -> None:
    for hook in list(_metrics_hooks):
        try:
            hook(metric, value, tags)
        except Exception:  # noqa: BLE001
            logger.exception("metrics hook %r failed for metric %s", hook, metric)


def set_cascade_config(cascade_tables: List[str] | None = None) -> None:
    """Restrict the hard-delete cascade to the given table names (None = all)."""
    global _cascade_tables
    if cascade_tables is None:
        _cascade_tables = None
        return
    if not isinstance(cascade_tables, list):
        raise CascadeConfigError("cascade_tables must be a list")
    if not cascade_tables:
        raise CascadeConfigError("cascade_tables must not be empty")
    _cascade_tables = list(cascade_tables)


# ---------------------------------------------------------------------------
# Core deletion API
# ---------------------------------------------------------------------------

def soft_delete_account(db: Session, user_id: int, *, actor_user_id: int | None = None,
                        reason: str = "") -> Dict[str, Any]:
    """Reversibly delete an account: deactivate the user and register the deletion."""
    from scrapyard.identity.users import User

    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(f"user {user_id} not found")
    user.is_active = False
    record = DeletionRecord(user_id=user_id, actor_user_id=actor_user_id,
                            reason=reason, method="soft")
    db.add(record)
    db.flush()
    emit_deletion_event("account.soft_deleted",
                        {"user_id": user_id, "actor_user_id": actor_user_id,
                         "target": f"user:{user_id}"})
    _emit_metric("accounts_soft_deleted", 1, {"actor": actor_user_id})
    return {"user_id": user_id, "method": "soft", "registry_id": record.id}


def _cascade_counts(db: Session, user_id: int, *, execute: bool) -> Dict[str, int]:
    """Count (and optionally delete) rows referencing user_id across mapped tables."""
    from scrapyard.identity.users import User
    from sqlalchemy import func as _func

    counts: Dict[str, int] = {}
    for mapper in User.registry.mappers:
        model = mapper.class_
        cols = {c.key for c in inspect(model).columns}
        # The deletion registry itself is excluded: it stores only the numeric
        # user_id (pseudonymous) and is retained as proof of erasure.
        if model is User or model is DeletionRecord or "user_id" not in cols:
            continue
        if _cascade_tables is not None and model.__tablename__ not in _cascade_tables:
            continue
        if execute:
            res = db.execute(delete(model).where(model.user_id == user_id))
            counts[model.__tablename__] = res.rowcount or 0
        else:
            n = db.execute(
                select(_func.count()).select_from(model).where(model.user_id == user_id)
            ).scalar() or 0
            counts[model.__tablename__] = int(n)
    return counts


def delete_account(db: Session, user_id: int, *, actor_user_id: int | None = None,
                   dry_run: bool = False, confirm: bool = False) -> dict:
    """Erase a user and all rows that reference them via a user_id column (GDPR
    'right to erasure'), writing an audit record of the action.

    SAFE BY DEFAULT: without ``confirm=True`` (or with ``dry_run=True``) nothing
    is deleted - the function returns the per-table counts that WOULD be removed,
    flagged with ``dry_run: True``. Only ``confirm=True`` with ``dry_run=False``
    performs the destructive cascade.
    """
    from scrapyard.identity.users import User
    from scrapyard.admin.audit_logs import record

    user = db.get(User, user_id)
    if user is None:
        return {"error": "not found"}

    effective_dry_run = dry_run or not confirm
    counts = _cascade_counts(db, user_id, execute=not effective_dry_run)

    if effective_dry_run:
        counts["users"] = 1
        return {"dry_run": True, "confirmed": bool(confirm), "counts": counts}

    record(db, action="account_deletion", actor_user_id=actor_user_id or user_id,
           target=f"user:{user_id}", detail="erased user and related records")
    # Register the hard deletion so compliance reporting can prove erasure.
    db.add(DeletionRecord(user_id=user_id, actor_user_id=actor_user_id,
                          reason="hard delete", method="hard", purged=True,
                          purged_at=datetime.now(timezone.utc)))
    db.delete(user)
    db.flush()
    counts["users"] = 1
    emit_deletion_event("account.deleted",
                        {"user_id": user_id, "actor_user_id": actor_user_id,
                         "target": f"user:{user_id}", "counts": dict(counts)})
    _emit_metric("accounts_hard_deleted", 1, {"actor": actor_user_id})
    return counts


def delete_account_with_filter(db: Session, user_id: int, *, filter_expr: str,
                               actor_user_id: int | None = None,
                               dry_run: bool = False, confirm: bool = False) -> Dict[str, Any]:
    """Delete an account only if the user row matches *filter_expr*.

    The expression is parsed structurally (``column op literal``) and evaluated
    in Python against the user object - it is never eval()'d.
    """
    from scrapyard.identity.users import User

    try:
        filter_obj = DeletionFilter(filter_expr)
    except InvalidFilterError as e:
        return {"error": str(e)}

    user = db.get(User, user_id)
    if user is None:
        return {"error": "not found"}
    try:
        if not filter_obj.matches(user):
            return {"skipped": True, "reason": f"user {user_id} does not match filter {filter_expr!r}"}
    except InvalidFilterError as e:
        return {"error": str(e)}

    return delete_account(db, user_id, actor_user_id=actor_user_id,
                          dry_run=dry_run, confirm=confirm)


def bulk_delete_accounts(db: Session, user_ids: List[int], *, actor_user_id: int | None = None,
                         policy: SoftDeletePolicy | None = None,
                         dry_run: bool = False, confirm: bool = False) -> dict:
    """Delete many accounts under a policy.

    With a soft-delete policy (the default) every account is reversibly
    deactivated and registered. With ``enable_soft_delete=False`` the hard
    cascade is used, which requires ``confirm=True`` to actually delete.
    """
    if not user_ids or not isinstance(user_ids, list):
        raise BulkDeleteLimitExceeded("user_ids must be a non-empty list")
    if len(user_ids) > 1000:
        raise BulkDeleteLimitExceeded("user_ids list exceeds maximum allowed size")

    if policy is None:
        policy = SoftDeletePolicy()

    results: Dict[str, Any] = {"requested": len(user_ids), "deleted_users": 0,
                               "not_found": [], "results": {}}
    for uid in user_ids:
        try:
            if policy.enable_soft_delete:
                results["results"][uid] = soft_delete_account(
                    db, uid, actor_user_id=actor_user_id, reason="bulk delete")
            else:
                out = delete_account(db, uid, actor_user_id=actor_user_id,
                                     dry_run=dry_run, confirm=confirm)
                if out.get("error"):
                    raise UserNotFoundError(str(uid))
                results["results"][uid] = out
            results["deleted_users"] += 1
        except UserNotFoundError:
            results["not_found"].append(uid)
    _emit_metric("accounts_bulk_deleted", results["deleted_users"],
                 {"actor": actor_user_id, "soft": policy.enable_soft_delete})
    return results


# ---------------------------------------------------------------------------
# Registry queries, purge, serialization
# ---------------------------------------------------------------------------

def list_deleted_accounts(db: Session, *, page: int = 1, per_page: int = 20,
                          actor_user_id: int | None = None,
                          include_purged: bool = False) -> list[dict]:
    """List registered account deletions, newest first, paginated."""
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page must be positive")
    stmt = select(DeletionRecord).order_by(DeletionRecord.deleted_at.desc(),
                                           DeletionRecord.id.desc())
    if not include_purged:
        stmt = stmt.where(DeletionRecord.purged.is_(False))
    if actor_user_id is not None:
        stmt = stmt.where(DeletionRecord.actor_user_id == actor_user_id)
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    rows = db.execute(stmt).scalars().all()
    return [serialize_deletion_result(r.to_dict()) for r in rows]


def purge_deleted_records(db: Session, *, max_age_days: int = 30,
                          actor_user_id: int | None = None,
                          limit: int = 1000) -> dict:
    """Hard-delete accounts whose soft deletion is older than *max_age_days*.

    Returns real counts: purged registry records and per-table cascade totals.
    """
    if max_age_days < 0:
        raise ValueError("max_age_days must be >= 0")
    if limit < 1:
        raise PurgeLimitExceeded("limit must be positive")

    from scrapyard.identity.users import User
    from scrapyard.admin.audit_logs import record as audit_record

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    stmt = (select(DeletionRecord)
            .where(DeletionRecord.purged.is_(False))
            .order_by(DeletionRecord.deleted_at.asc())
            .limit(limit))
    pending = db.execute(stmt).scalars().all()

    total_rows = 0
    table_totals: Dict[str, int] = {}
    purged_records = 0
    for rec in pending:
        deleted_at = rec.deleted_at
        if deleted_at is not None and deleted_at.tzinfo is None:
            deleted_at = deleted_at.replace(tzinfo=timezone.utc)
        if deleted_at is not None and deleted_at > cutoff:
            continue
        counts = _cascade_counts(db, rec.user_id, execute=True)
        user = db.get(User, rec.user_id)
        if user is not None:
            db.delete(user)
            counts["users"] = 1
        for table, n in counts.items():
            table_totals[table] = table_totals.get(table, 0) + n
            total_rows += n
        rec.purged = True
        rec.purged_at = datetime.now(timezone.utc)
        purged_records += 1
    if purged_records:
        db.flush()
        audit_record(db, action="account_purge", actor_user_id=actor_user_id,
                     target=f"records:{purged_records}",
                     detail=f"purged {purged_records} soft-deleted accounts older than {max_age_days}d")
        emit_deletion_event("account.purged",
                            {"target": "purge", "purged_records": purged_records,
                             "row_counts": dict(table_totals)})
        _emit_metric("accounts_purged", purged_records, {"actor": actor_user_id})
    return {"deleted_records": purged_records, "rows_removed": total_rows,
            "tables": table_totals}


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def serialize_deletion_result(result: dict) -> dict:
    """Normalize a deletion/registry result into a JSON-serializable dict."""
    if not isinstance(result, dict):
        raise SerializationError("result must be a dict")
    out = _json_safe(result)
    try:
        json.dumps(out)
    except (TypeError, ValueError) as e:  # pragma: no cover - _json_safe should prevent
        raise SerializationError(str(e)) from e
    return out


def serialize_account_export(db: Session, user_id: int) -> str:
    """Serialize everything stored about a user to a JSON string (GDPR export)."""
    from scrapyard.compliance.data_export import export_user_data

    data = export_user_data(db, user_id)
    try:
        return json.dumps(_json_safe(data), indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise SerializationError(str(e)) from e


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> None:
    """Offline self-test with a temporary SQLite database."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _Session, Mapped as _Mapped

    from scrapyard.database.base_model import Base
    from scrapyard.identity.users import User
    import scrapyard.admin.audit_logs  # noqa: F401 - register audit_logs table before create_all

    # Related table with a user_id column to prove the cascade is real.
    global _SelftestNote
    try:
        _SelftestNote
    except NameError:
        class _SelftestNote(IntPKModel):  # type: ignore[no-redef]
            __tablename__ = "account_deletion_selftest_notes"
            user_id: Mapped[int] = mapped_column(Integer, nullable=False)
            text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        Base.metadata.create_all(engine)
        try:
            with _Session(engine) as db:
                # Seed two users with related rows.
                u1 = User(email="erase.me@example.com", password_hash="x")
                u2 = User(email="keep.me@example.com", password_hash="x")
                db.add_all([u1, u2])
                db.flush()
                db.add_all([_SelftestNote(user_id=u1.id, text="a"),
                            _SelftestNote(user_id=u1.id, text="b"),
                            _SelftestNote(user_id=u2.id, text="c")])
                db.commit()
                uid1, uid2 = u1.id, u2.id

                # Working hook registry: hooks actually fire.
                events: List[tuple] = []
                metrics: List[tuple] = []
                unhook = register_audit_hook(lambda et, tgt, st, pl: events.append((et, tgt)))
                unmetr = register_metrics_hook(lambda m, v, t: metrics.append((m, v)))
                try:
                    register_audit_hook("not callable")
                    raise AssertionError("expected AuditHookError")
                except AuditHookError:
                    pass

                # emit_deletion_event fires hooks and validates input.
                assert emit_deletion_event("test.event", {"target": "t"}) == 1
                assert events == [("test.event", "t")]
                try:
                    emit_deletion_event("", {"x": 1})
                    raise AssertionError("expected ValueError")
                except ValueError:
                    pass

                # SAFE DEFAULT: no confirm -> dry run, nothing deleted.
                out = delete_account(db, uid1)
                assert out["dry_run"] is True
                assert out["counts"]["account_deletion_selftest_notes"] == 2
                assert db.get(User, uid1) is not None
                out = delete_account(db, uid1, confirm=True, dry_run=True)
                assert out["dry_run"] is True and db.get(User, uid1) is not None

                # Soft delete: registry row + deactivation.
                res = soft_delete_account(db, uid1, actor_user_id=99, reason="user request")
                db.commit()
                assert res["method"] == "soft"
                assert db.get(User, uid1).is_active is False
                listed = list_deleted_accounts(db)
                assert len(listed) == 1 and listed[0]["user_id"] == uid1
                assert isinstance(listed[0]["deleted_at"], str)  # JSON-safe
                try:
                    soft_delete_account(db, 424242)
                    raise AssertionError("expected UserNotFoundError")
                except UserNotFoundError:
                    pass

                # Purge: too-new records survive, aged records get hard-deleted.
                assert purge_deleted_records(db, max_age_days=30)["deleted_records"] == 0
                assert db.get(User, uid1) is not None
                purged = purge_deleted_records(db, max_age_days=0)
                db.commit()
                assert purged["deleted_records"] == 1
                assert purged["tables"]["account_deletion_selftest_notes"] == 2
                assert purged["tables"]["users"] == 1
                assert db.get(User, uid1) is None
                assert db.execute(select(_SelftestNote)
                                  .where(_SelftestNote.user_id == uid1)).scalars().all() == []
                # u2 untouched
                assert db.get(User, uid2) is not None
                assert list_deleted_accounts(db) == []  # purged excluded by default
                assert len(list_deleted_accounts(db, include_purged=True)) == 1

                # Filtered delete: mismatch skips, match (with confirm) deletes.
                u3 = User(email="filter.me@example.com", password_hash="x", is_active=True)
                db.add(u3)
                db.commit()
                r = delete_account_with_filter(db, u3.id, filter_expr="is_active == false",
                                               confirm=True)
                assert r.get("skipped") is True and db.get(User, u3.id) is not None
                r = delete_account_with_filter(db, u3.id, filter_expr="is_active == true",
                                               confirm=True)
                db.commit()
                assert r.get("users") == 1 and db.get(User, u3.id) is None
                assert "error" in delete_account_with_filter(db, uid2, filter_expr="")
                assert "error" in delete_account_with_filter(db, uid2, filter_expr="no_such_col == 1")

                # Bulk soft delete under default policy.
                u4 = User(email="bulk1@example.com", password_hash="x")
                u5 = User(email="bulk2@example.com", password_hash="x")
                db.add_all([u4, u5])
                db.commit()
                bulk = bulk_delete_accounts(db, [u4.id, u5.id, 999999], actor_user_id=1)
                db.commit()
                assert bulk["deleted_users"] == 2 and bulk["not_found"] == [999999]
                assert db.get(User, u4.id).is_active is False
                try:
                    bulk_delete_accounts(db, [])
                    raise AssertionError("expected BulkDeleteLimitExceeded")
                except BulkDeleteLimitExceeded:
                    pass

                # Serialization: JSON-safe results and full GDPR export.
                ser = serialize_deletion_result({"when": datetime.now(timezone.utc),
                                                 "ids": {1, 2}, "nested": {"d": date(2024, 1, 1)}})
                json.dumps(ser)  # must not raise
                export = serialize_account_export(db, uid2)
                parsed = json.loads(export)
                assert parsed["users"][0]["email"] == "keep.me@example.com"

                # Cascade config restricts the cascade.
                try:
                    set_cascade_config([])
                    raise AssertionError("expected CascadeConfigError")
                except CascadeConfigError:
                    pass
                set_cascade_config(["account_deletion_selftest_notes"])
                try:
                    dry = delete_account(db, uid2)  # dry run
                    assert set(dry["counts"].keys()) == {"account_deletion_selftest_notes", "users"}
                finally:
                    set_cascade_config(None)

                # Hooks fired for real deletions along the way.
                fired_types = {e[0] for e in events}
                assert "account.soft_deleted" in fired_types
                assert "account.deleted" in fired_types
                assert "account.purged" in fired_types
                assert any(m[0] == "accounts_purged" for m in metrics)

                unhook()
                unmetr()
                assert emit_deletion_event("post.unhook", {"target": "t"}) == 0
        finally:
            engine.dispose()

    print("account_deletion self-test passed")


if __name__ == "__main__":
    _selftest()
