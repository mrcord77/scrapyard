"""
field_encryption — Encrypt sensitive columns at rest.

### PART-META-JSON
{
  "name": "field_encryption",
  "layer": "security",
  "purpose": "Encrypt sensitive columns at rest.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "cryptography"
  ],
  "inputs": "Public API: encrypt(plaintext, key); decrypt(token, key); generate_key().",
  "outputs": "Returns: encrypt -> str; decrypt -> str; generate_key -> str.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control. Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `encrypt` from `scrapyard.security.field_encryption` and call it as shown in `example`; run `py -m scrapyard.security.field_encryption` to see its offline selftest.",
  "example": "from scrapyard.security.field_encryption import encrypt",
  "import_path": "scrapyard.security.field_encryption"
}
### END-PART-META
"""
from __future__ import annotations
import base64
import hashlib
import os

STATUS = "core"


def _fernet(key: str | None = None):
    """Build a Fernet from a provided key or the FIELD_ENCRYPTION_KEY env var.
    A valid Fernet key is required; an invalid value fails loudly rather than
    silently deriving a weaker key from it (a typo'd/truncated key must never pass
    unnoticed). Set SCRAPYARD_ALLOW_DERIVED_KEY=1 to derive from a passphrase on
    purpose (weaker; not for production). cryptography is imported lazily."""
    from cryptography.fernet import Fernet
    raw = key or os.environ.get("FIELD_ENCRYPTION_KEY")
    if not raw:
        raise RuntimeError("FIELD_ENCRYPTION_KEY not set (or pass key=)")
    rawb = raw if isinstance(raw, bytes) else raw.encode()
    try:
        return Fernet(rawb)
    except Exception:
        if os.environ.get("SCRAPYARD_ALLOW_DERIVED_KEY") == "1":
            digest = hashlib.sha256(rawb).digest()
            return Fernet(base64.urlsafe_b64encode(digest))
        raise RuntimeError(
            "FIELD_ENCRYPTION_KEY is not a valid Fernet key. Mint one with "
            "scrapyard.security.field_encryption.generate_key(). To derive a key "
            "from a passphrase on purpose, set SCRAPYARD_ALLOW_DERIVED_KEY=1 "
            "(weaker; not recommended for production)."
        ) from None


def encrypt(plaintext: str, key: str | None = None) -> str:
    if plaintext is None:
        return None
    return _fernet(key).encrypt(plaintext.encode()).decode()


def decrypt(token: str, key: str | None = None) -> str:
    if token is None:
        return None
    return _fernet(key).decrypt(token.encode()).decode()


def generate_key() -> str:
    """Mint a fresh Fernet key (store it as FIELD_ENCRYPTION_KEY; rotate carefully)."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


try:
    from sqlalchemy.types import TypeDecorator, Text as _Text

    class EncryptedString(TypeDecorator):
        """A SQLAlchemy column type that encrypts on write, decrypts on read.

        Usage:  body: Mapped[str] = mapped_column(EncryptedString)
        Reads FIELD_ENCRYPTION_KEY at flush/load time."""
        impl = _Text
        cache_ok = True

        def process_bind_param(self, value, dialect):
            return encrypt(value) if value is not None else None

        def process_result_value(self, value, dialect):
            return decrypt(value) if value is not None else None
except Exception:  # sqlalchemy not installed at import time
    EncryptedString = None


def _selftest() -> None:
    """Offline, falsifiable self-test. Skips gracefully if `cryptography` absent."""
    try:
        from cryptography.fernet import Fernet  # noqa: F401
    except Exception:
        print("field_encryption: SKIPPED (cryptography not installed)")
        return

    key = generate_key()
    pt = "patient-mrn-0009 ❤ secret"

    # 1) roundtrip: decrypt(encrypt(x)) == x
    ct = encrypt(pt, key)
    assert decrypt(ct, key) == pt, "decrypt(encrypt(x)) must equal x"

    # 2) NEGATIVE: ciphertext must NOT equal plaintext (real encryption happened)
    assert ct != pt and pt not in ct, "ciphertext must not reveal plaintext"

    # 3) NEGATIVE: a DIFFERENT key must fail to decrypt (InvalidToken)
    other = generate_key()
    failed = False
    try:
        decrypt(ct, other)
    except Exception:
        failed = True
    assert failed, "decrypting with the wrong key must fail"

    # 4) non-determinism: two encryptions of the same value differ (fresh IV)
    assert encrypt(pt, key) != encrypt(pt, key), "each encryption must use a fresh IV"

    # 5) None passes through untouched
    assert encrypt(None, key) is None and decrypt(None, key) is None

    print("field_encryption: OK (5 assertions incl. wrong-key + ciphertext!=plaintext negatives)")


if __name__ == "__main__":
    _selftest()
