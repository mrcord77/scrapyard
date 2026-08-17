"""
privacy_policy_hooks — Surface + version privacy policy acceptance.

### PART-META-JSON
{
  "name": "privacy_policy_hooks",
  "layer": "compliance",
  "purpose": "Central privacy machinery: a PrivacyRegistry that marks sensitive fields and redacts them for logging, plus a PrivacyPolicyRegistry that versions privacy policies, records per-user acceptance in a real table, and checks compliance against the current policy.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: redact_for_logging(data); PrivacyRegistry(...); PolicyVersionNotFoundError(...); PolicyAlreadyExistsError(...) (plus more).",
  "outputs": "Returns: redact_for_logging -> dict.",
  "files_created": [],
  "security_notes": "redact_for_logging masks registered sensitive fields ('***') - register every new secret/PII field via registry.mark_sensitive or it WILL pass through to logs. Policy content is stored/rendered verbatim: escape on render if displayed as HTML. Acceptance rows link user ids to policy versions (auditable PII linkage) - restrict read access. No authorization checks: enforce who may register or archive policy versions in the calling layer.",
  "ai_usage": "Use redact_for_logging before logging user dicts; instantiate PrivacyPolicyRegistry(db_session) for policy versioning and acceptance tracking.",
  "example": "from scrapyard.compliance.privacy_policy_hooks import redact_for_logging",
  "import_path": "scrapyard.compliance.privacy_policy_hooks"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

class PrivacyRegistry:
    """Central registry of which fields are sensitive, so logging/serialization can
    consistently redact them and so we never write PII to logs."""
    def __init__(self):
        self._sensitive: set[str] = {"password", "password_hash", "token", "ssn", "body"}
        self._no_log: set[str] = set(self._sensitive)
    def mark_sensitive(self, *fields: str):
        self._sensitive.update(fields); self._no_log.update(fields)
    def is_sensitive(self, field: str) -> bool:
        return field in self._sensitive
    def should_log(self, field: str) -> bool:
        return field not in self._no_log
    def redact(self, data: dict) -> dict:
        return {k: ("***" if k in self._sensitive else v) for k, v in data.items()}

registry = PrivacyRegistry()
def redact_for_logging(data: dict) -> dict:
    return registry.redact(data)

from datetime import datetime
import uuid
from typing import Any, Dict, List, Optional, TypeVar
from sqlalchemy.orm import Session
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

T = TypeVar('T')

class PolicyVersionNotFoundError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=404, detail=detail)

class PolicyAlreadyExistsError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=409, detail=detail)

class InvalidPolicyContentError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=422, detail=detail)

class UserNotAuthorizedError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=403, detail=detail)

class PolicyExpiredError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=410, detail=detail)

class InvalidDateFormatError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=422, detail=detail)

class BulkOperationLimitExceeded(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=400, detail=detail)

class PrivacyPolicy(BaseModel):
    version: str
    content: str
    effective_from: datetime
    expires: Optional[datetime] = None

class PolicyVersion:
    def __init__(self, version: str, content: str, effective_from: datetime, expires: Optional[datetime] = None):
        self.version = version
        self.content = content
        self.effective_from = effective_from
        self.expires = expires

from scrapyard.database.base_model import IntPKModel
from sqlalchemy import String as _String
from sqlalchemy.orm import mapped_column as _mapped_column


class UserPolicyAcceptance(IntPKModel):
    """Per-user policy acceptance record (real table, replaces raw-SQL stub)."""

    __tablename__ = "privacy_policy_hooks_acceptance"
    user_id = _mapped_column(_String(64), nullable=False, index=True)
    policy_version = _mapped_column(_String(64), nullable=False)


class PrivacyPolicyRegistry:
    def __init__(self, db_session: Session):
        self.db_session = db_session
        self._policy_versions: Dict[str, PolicyVersion] = {}
        self._hook_events: List[Dict[str, Any]] = []

    def register_policy_version(self, version: str, content: str, effective_from: datetime, expires: Optional[datetime] = None) -> PolicyVersion:
        if version in self._policy_versions:
            raise PolicyAlreadyExistsError(f"Policy version {version} already exists.")
        if not content or not content.strip():
            raise InvalidPolicyContentError("Policy content must be non-empty.")
        # Validate the payload with the pydantic schema (never add a pydantic
        # model to a SQLAlchemy session - that was a bug).
        policy = PrivacyPolicy(version=version, content=content, effective_from=effective_from, expires=expires)
        self._policy_versions[version] = PolicyVersion(
            version=policy.version,
            content=policy.content,
            effective_from=policy.effective_from,
            expires=policy.expires,
        )
        return self._policy_versions[version]

    def get_current_policy(self) -> Optional[str]:
        now = datetime.now()
        active = [v for v in self._policy_versions.values()
                  if v.effective_from <= now and (v.expires is None or v.expires > now)]
        if not active:
            return None
        current = max(active, key=lambda v: v.effective_from)
        return current.content

    def get_current_policy_version(self) -> Optional[str]:
        now = datetime.now()
        active = [v for v in self._policy_versions.values()
                  if v.effective_from <= now and (v.expires is None or v.expires > now)]
        if not active:
            return None
        return max(active, key=lambda v: v.effective_from).version

    def get_policy_version(self, version: str) -> PolicyVersion:
        if version not in self._policy_versions:
            raise PolicyVersionNotFoundError(f"Policy version {version} does not exist.")
        return self._policy_versions[version]

    def list_policy_versions(self, limit: int = 100, offset: int = 0) -> List[PolicyVersion]:
        versions = sorted(self._policy_versions.values(), key=lambda v: (v.effective_from, -len(v.version)))
        return versions[offset:offset+limit]

    def archive_policy_version(self, version: str) -> PolicyVersion:
        """Archive a policy version: mark it expired now (idempotent)."""
        policy = self.get_policy_version(version)
        now = datetime.now()
        if policy.expires is None or policy.expires > now:
            policy.expires = now
        return policy

    def audit_policy_changes(self, old_version: str, new_version: str) -> Dict[str, Any]:
        """Word-level diff between two policy versions: added/removed words."""
        old_words = set(self.get_policy_version(old_version).content.split())
        new_words = set(self.get_policy_version(new_version).content.split())
        return {
            "added": sorted(new_words - old_words),
            "removed": sorted(old_words - new_words),
        }

    def apply_policy_to_user(self, user_id: uuid.UUID, policy_version: str):
        self.get_policy_version(policy_version)  # Ensure version exists
        try:
            self.db_session.add(UserPolicyAcceptance(user_id=str(user_id),
                                                     policy_version=policy_version))
            self.db_session.commit()
        except SQLAlchemyError as e:
            self.db_session.rollback()
            raise UserNotAuthorizedError(f"Failed to apply policy: {e}")

    def get_user_policy_acceptance(self, user_id: uuid.UUID) -> Optional[str]:
        try:
            from sqlalchemy import select as _select
            row = self.db_session.scalars(
                _select(UserPolicyAcceptance)
                .where(UserPolicyAcceptance.user_id == str(user_id))
                .order_by(UserPolicyAcceptance.id.desc())
            ).first()
            return row.policy_version if row else None
        except SQLAlchemyError as e:
            raise UserNotAuthorizedError(f"Failed to get user policy acceptance: {e}")

    def check_policy_compliance(self, user_id: uuid.UUID) -> bool:
        latest_version = self.get_current_policy_version()
        current_acceptance = self.get_user_policy_acceptance(user_id)
        return latest_version is not None and latest_version == current_acceptance

    def bulk_apply_policy_to_users(self, user_ids: List[uuid.UUID], policy_version: str):
        if len(user_ids) > 100:
            raise BulkOperationLimitExceeded("Bulk operation limit exceeded.")
        for user_id in user_ids:
            self.apply_policy_to_user(user_id, policy_version)

    def serialize_policy(self, policy_version: str, format: str = "json") -> Dict[str, Any]:
        policy = self.get_policy_version(policy_version)
        if format == "json":
            return {"version": policy.version, "content": policy.content}
        else:
            raise ValueError("Unsupported serialization format")

    def policy_hook_before_save(self, obj: Any, policy_version: str):
        self.get_policy_version(policy_version)
        event = {"phase": "before_save", "policy_version": policy_version,
                 "object_type": type(obj).__name__}
        self._hook_events.append(event)
        return event

    def policy_hook_after_save(self, obj: Any, policy_version: str):
        self.get_policy_version(policy_version)
        event = {"phase": "after_save", "policy_version": policy_version,
                 "object_type": type(obj).__name__}
        self._hook_events.append(event)
        return event

    def policy_hook_on_archive(self, version: str):
        policy = self.archive_policy_version(version)
        event = {"phase": "archive", "policy_version": version,
                 "expired_at": policy.expires}
        self._hook_events.append(event)
        return event


def _selftest() -> None:
    """Offline self-test: redaction registry + policy versioning/acceptance."""
    import os
    import tempfile
    from datetime import timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from scrapyard.database.base_model import IntPKModel as _M

    # Redaction registry
    data = {"email": "a@b.c", "password": "secret", "token": "t"}
    red = redact_for_logging(data)
    assert red["password"] == "***" and red["token"] == "***" and red["email"] == "a@b.c"
    registry.mark_sensitive("email")
    assert redact_for_logging(data)["email"] == "***"
    assert registry.is_sensitive("password") and not registry.should_log("password")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'test.db')}")
        _M.metadata.create_all(engine)
        try:
            with _S(engine) as db:
                reg = PrivacyPolicyRegistry(db)
                assert reg.get_current_policy() is None  # empty registry must not crash

                t0 = datetime.now() - timedelta(days=30)
                reg.register_policy_version("1.0", "we collect data", t0)
                reg.register_policy_version("2.0", "we collect and share data",
                                            datetime.now() - timedelta(days=1))
                try:
                    reg.register_policy_version("1.0", "dup", t0)
                    raise AssertionError("expected PolicyAlreadyExistsError")
                except PolicyAlreadyExistsError:
                    pass
                try:
                    reg.register_policy_version("3.0", "   ", t0)
                    raise AssertionError("expected InvalidPolicyContentError")
                except InvalidPolicyContentError:
                    pass

                assert reg.get_current_policy() == "we collect and share data"
                assert reg.get_current_policy_version() == "2.0"
                assert reg.get_policy_version("1.0").content == "we collect data"
                try:
                    reg.get_policy_version("9.9")
                    raise AssertionError("expected PolicyVersionNotFoundError")
                except PolicyVersionNotFoundError:
                    pass

                diff = reg.audit_policy_changes("1.0", "2.0")
                assert diff["added"] == ["and", "share"] and diff["removed"] == []

                uid = uuid.uuid4()
                assert reg.get_user_policy_acceptance(uid) is None
                assert reg.check_policy_compliance(uid) is False
                reg.apply_policy_to_user(uid, "1.0")
                assert reg.get_user_policy_acceptance(uid) == "1.0"
                assert reg.check_policy_compliance(uid) is False  # outdated version
                reg.apply_policy_to_user(uid, "2.0")
                assert reg.check_policy_compliance(uid) is True

                # Bulk apply + limit
                users = [uuid.uuid4() for _ in range(3)]
                reg.bulk_apply_policy_to_users(users, "2.0")
                assert all(reg.check_policy_compliance(u) for u in users)
                try:
                    reg.bulk_apply_policy_to_users([uuid.uuid4()] * 101, "2.0")
                    raise AssertionError("expected BulkOperationLimitExceeded")
                except BulkOperationLimitExceeded:
                    pass

                # Serialization + archive
                assert reg.serialize_policy("2.0") == {"version": "2.0",
                                                       "content": "we collect and share data"}
                before = reg.policy_hook_before_save({"id": 1}, "2.0")
                after = reg.policy_hook_after_save({"id": 1}, "2.0")
                archived = reg.policy_hook_on_archive("2.0")
                assert [before["phase"], after["phase"], archived["phase"]] == \
                    ["before_save", "after_save", "archive"]
                assert len(reg._hook_events) == 3
                assert reg.get_current_policy_version() == "1.0"  # 2.0 expired
                reg.archive_policy_version("2.0")  # idempotent
        finally:
            engine.dispose()
    print("privacy_policy_hooks self-test passed")


if __name__ == "__main__":
    _selftest()
