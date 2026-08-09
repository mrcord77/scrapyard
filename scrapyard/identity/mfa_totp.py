"""
mfa_totp — TOTP enrollment + verification (RFC 6238).

### PART-META-JSON
{
  "name": "mfa_totp",
  "layer": "identity",
  "purpose": "TOTP enrollment + verification (RFC 6238).",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "Public API: generate_secret(); totp(secret, *, t, step, digits); verify(secret, code, *, t, step, window); on_totp_event(hook); provisioning_uri(secret, *, account, issuer, digits, step); TOTPDevice(...); TOTPPolicy(...); TOTPError(...) (plus more).",
  "outputs": "Returns: generate_secret -> str; totp -> str; verify -> bool; on_totp_event -> None; provisioning_uri -> str.",
  "files_created": [],
  "security_notes": "TOTP secrets are credentials: store them encrypted at rest (pair with security.field_encryption) and never log them or embed them in error messages.",
  "ai_usage": "Import `generate_secret` from `scrapyard.identity.mfa_totp` and call it as shown in `example`; run `py -m scrapyard.identity.mfa_totp` to see its offline selftest.",
  "example": "from scrapyard.identity.mfa_totp import generate_secret",
  "import_path": "scrapyard.identity.mfa_totp"
}
### END-PART-META
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets as _secrets
import struct
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

from sqlalchemy import DateTime, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from scrapyard.database.base_model import IntPKModel

STATUS = "core"

log = logging.getLogger("scrapyard.identity.mfa_totp")


# -- original core API (RFC 6238 primitives) -------------------------------------
def generate_secret() -> str:
    return base64.b32encode(_secrets.token_bytes(20)).decode()


def totp(secret: str, *, t: int | None = None, step: int = 30,
         digits: int = 6) -> str:
    key = base64.b32decode(secret)
    counter = int((t if t is not None else time.time()) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def verify(secret: str, code: str, *, t: int | None = None, step: int = 30,
           window: int = 1) -> bool:
    """Constant-time comparison across +/- `window` steps of clock drift."""
    now = int(t if t is not None else time.time())
    return any(
        hmac.compare_digest(totp(secret, t=now + o * step, step=step), code)
        for o in range(-window, window + 1)
    )


# -- device enrollment (persistent, multi-device) --------------------------------
class TOTPDevice(IntPKModel):
    __tablename__ = "totp_devices"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    secret: Mapped[str] = mapped_column(String(64))
    issuer: Mapped[str] = mapped_column(String(120), default="Scrapyard")
    name: Mapped[str] = mapped_column(String(120), default="default")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    deactivation_reason: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True)


@dataclass
class TOTPPolicy:
    digits: int = 6
    step: int = 30
    window: int = 1
    max_devices_per_user: int = 10


class TOTPError(Exception):
    pass


class DeviceNotFoundError(TOTPError):
    pass


class DeviceLimitError(TOTPError):
    pass


# event hooks: fn(event_type, user_id, device_id)
_EVENTS: List[Callable[[str, int, Optional[int]], None]] = []


def on_totp_event(hook: Callable[[str, int, Optional[int]], None]) -> None:
    _EVENTS.append(hook)


def _fire(event: str, user_id: int, device_id: Optional[int] = None) -> None:
    for h in _EVENTS:
        try:
            h(event, user_id, device_id)
        except Exception:  # noqa: BLE001 - observers must not break MFA
            log.exception("totp event hook failed for %s", event)


class TOTPService:
    """Multi-device TOTP enrollment/verification backed by the database."""

    def __init__(self, db: Session, policy: TOTPPolicy | None = None):
        self.db = db
        self.policy = policy or TOTPPolicy()

    def _active_devices(self, user_id: int) -> List[TOTPDevice]:
        stmt = select(TOTPDevice).where(
            TOTPDevice.user_id == user_id, TOTPDevice.deleted_at.is_(None))
        return list(self.db.scalars(stmt))

    def enroll(self, user_id: int, *, issuer: str = "Scrapyard",
               name: str = "default") -> TOTPDevice:
        if len(self._active_devices(user_id)) >= self.policy.max_devices_per_user:
            raise DeviceLimitError(
                f"user {user_id} already has {self.policy.max_devices_per_user} devices")
        device = TOTPDevice(user_id=user_id, secret=generate_secret(),
                            issuer=issuer, name=name)
        self.db.add(device)
        self.db.flush()
        _fire("enrolled", user_id, device.id)
        return device

    def verify(self, user_id: int, code: str) -> bool:
        """True if `code` matches ANY of the user's active devices."""
        for device in self._active_devices(user_id):
            if verify(device.secret, code, step=self.policy.step,
                      window=self.policy.window):
                device.last_used_at = datetime.now(timezone.utc)
                self.db.flush()
                _fire("verified", user_id, device.id)
                return True
        _fire("verify_failed", user_id, None)
        return False

    def list_devices(self, user_id: int,
                     include_deleted: bool = False) -> List[TOTPDevice]:
        stmt = select(TOTPDevice).where(TOTPDevice.user_id == user_id)
        if not include_deleted:
            stmt = stmt.where(TOTPDevice.deleted_at.is_(None))
        return list(self.db.scalars(stmt.order_by(TOTPDevice.id)))

    def deactivate(self, device_id: int, *, reason: str | None = None) -> TOTPDevice:
        device = self.db.get(TOTPDevice, device_id)
        if device is None:
            raise DeviceNotFoundError(f"TOTP device {device_id} not found")
        device.deleted_at = datetime.now(timezone.utc)
        device.deactivation_reason = reason
        self.db.flush()
        _fire("deactivated", device.user_id, device.id)
        return device

    def bulk_deactivate(self, device_ids: List[int], *,
                        reason: str | None = None) -> List[TOTPDevice]:
        return [self.deactivate(d, reason=reason) for d in device_ids]


def provisioning_uri(secret: str, *, account: str, issuer: str = "Scrapyard",
                     digits: int = 6, step: int = 30) -> str:
    """otpauth:// URI for authenticator-app enrollment (render as QR client-side)."""
    label = urllib.parse.quote(f"{issuer}:{account}")
    query = urllib.parse.urlencode({
        "secret": secret, "issuer": issuer, "digits": digits, "period": step,
        "algorithm": "SHA1",
    })
    return f"otpauth://totp/{label}?{query}"


def _selftest() -> None:
    """Offline self-test: RFC6238 primitives (frozen time) + DB-backed service."""
    import os
    import tempfile
    from sqlalchemy import create_engine
    from scrapyard.database.base_model import Base

    # 1. Pure TOTP primitives with frozen time (fully deterministic).
    secret = generate_secret()
    frozen = 1_700_000_000
    code = totp(secret, t=frozen)
    assert len(code) == 6 and code.isdigit(), "TOTP must be 6 numeric digits"
    assert verify(secret, code, t=frozen), "correct code at same instant must verify"
    # negative: a code from 4 steps ago is outside window=1 and must be rejected
    stale = totp(secret, t=frozen - 4 * 30)
    assert not verify(secret, stale, t=frozen), "stale (expired) code must be rejected"
    # negative: a tampered code must not verify
    wrong = str((int(code) + 1) % 10 ** 6).zfill(6)
    assert not verify(secret, wrong, t=frozen), "wrong code must be rejected"

    # 2. DB-backed multi-device TOTPService.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        engine = create_engine(f"sqlite:///{os.path.join(tmp, 't.db')}")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as db:
                svc = TOTPService(db, TOTPPolicy(max_devices_per_user=1))
                dev = svc.enroll(42)
                assert dev.secret, "enroll must mint a device secret"
                good = totp(dev.secret)  # real 'now'; window=1 tolerates drift
                assert svc.verify(42, good), "service must accept a valid code"
                bad = str((int(good) + 1) % 10 ** 6).zfill(6)
                assert not svc.verify(42, bad), "service must reject a wrong code"
                # negative: per-user device limit is enforced
                try:
                    svc.enroll(42)
                    raise AssertionError("device limit must raise DeviceLimitError")
                except DeviceLimitError:
                    pass
                db.commit()
        finally:
            engine.dispose()
    print("mfa_totp self-test passed")


if __name__ == "__main__":
    _selftest()
