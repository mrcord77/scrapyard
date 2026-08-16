"""
pq_field_encryption — Encrypt sensitive columns at rest under hybrid post-quantum
key transport (envelope-of-DEK), so harvested ciphertext stays secret even once a
quantum computer breaks classical key exchange.

Each value is sealed with scrapyard.security.pq_envelope (X25519 + ML-KEM-768 ->
AES-256-GCM): the column data is AEAD-encrypted under a key derived from BOTH a
classical and a post-quantum shared secret. The recipient keypair is supplied via
env (or citadel custody). Decryption requires the recipient secret AND both KEM
shares, so copying the database is not enough — and a future quantum break of
X25519 alone does not expose the data.

### PART-META-JSON
{
  "name": "pq_field_encryption",
  "layer": "security",
  "purpose": "Encrypt sensitive columns at rest under hybrid post-quantum key transport (harvest-now-decrypt-later defense).",
  "addition": true,
  "status": "core",
  "dependencies": [
    "cryptography",
    "kyber-py",
    "sqlalchemy"
  ],
  "inputs": "PQEncryptedString(aad=...) as a SQLAlchemy column type; recipient keypair from env PQ_FIELD_PUBLIC / PQ_FIELD_SECRET (hex; PQ_FIELD_SECRET may be comma-separated for rotation).",
  "outputs": "Self-describing base64 envelope wire stored in the column; transparent decrypt on read.",
  "files_created": [],
  "security_notes": "Hybrid post-quantum at rest: data is recoverable only with the recipient secret AND both (X25519 + ML-KEM-768) shares, so a stolen database — or a future quantum break of X25519 alone — does not expose it. AAD binds each value to its table.column to resist ciphertext substitution. Key ROTATION is supported: PQ_FIELD_PUBLIC is the current recipient (new writes use it); PQ_FIELD_SECRET is a comma-separated list (current first, then retired) so values written under old keys still decrypt — rotate by prepending a new keypair and retiring old secrets once re-encrypted. Each stored wire stamps its suite id, so the at-rest format is migratable. In production, custody the secret in a secrets manager or citadel, never in the app image; never log the recipient secret. The local backend's ML-KEM is a correct FIPS 203 reference implementation, not constant-time/audited — set SCRAPYARD_CRYPTO_BACKEND=citadel for the production primitive.",
  "ai_usage": "generate_recipient() once; set PQ_FIELD_PUBLIC/PQ_FIELD_SECRET. Use PQEncryptedString(aad=b'table.col') as the column type for sensitive str/text fields (gen_models wires this for encrypted fields in sensitive domains). Pair with crypto_agility for suite/backend selection.",
  "example": "from scrapyard.security.pq_field_encryption import generate_recipient, pq_encrypt, pq_decrypt; pub, sec = generate_recipient(); w = pq_encrypt('secret', pub, aad=b'patients.mrn'); assert pq_decrypt(w, [sec], aad=b'patients.mrn') == 'secret'",
  "import_path": "scrapyard.security.pq_field_encryption"
}
### END-PART-META
"""
from __future__ import annotations
import base64
import os

STATUS = "core"


def generate_recipient() -> tuple[bytes, bytes]:
    """Mint a hybrid recipient keypair (delegates to pq_envelope)."""
    from scrapyard.security.pq_envelope import generate_recipient as _g
    return _g()


def generate_recipient_hex() -> tuple[str, str]:
    """Mint a keypair as hex strings for PQ_FIELD_PUBLIC / PQ_FIELD_SECRET."""
    pub, sec = generate_recipient()
    return pub.hex(), sec.hex()


def pq_encrypt(plaintext: str, recipient_public: bytes, aad: bytes = b"") -> str:
    """Seal a string to base64 hybrid-envelope wire."""
    if plaintext is None:
        return None
    from scrapyard.security.pq_envelope import seal
    wire = seal(plaintext.encode(), recipient_public, aad=aad)
    return base64.b64encode(wire).decode()


def pq_decrypt(token: str, recipient_secrets: list[bytes], aad: bytes = b"") -> str:
    """Open a base64 wire, trying each secret in turn (supports key rotation:
    values sealed under retired keys still decrypt)."""
    if token is None:
        return None
    from scrapyard.security.pq_envelope import open as _open
    wire = base64.b64decode(token)
    last = None
    for sk in recipient_secrets:
        try:
            return _open(wire, sk, aad=aad).decode()
        except Exception as e:  # try the next (rotated) key
            last = e
    raise RuntimeError("pq_field_encryption: no recipient key could decrypt this value "
                       "(wrong/rotated-out key, or tampered ciphertext)") from last


def _recipient_public() -> bytes:
    raw = os.environ.get("PQ_FIELD_PUBLIC")
    if not raw:
        raise RuntimeError(
            "PQ_FIELD_PUBLIC not set (this app encrypts fields at rest under hybrid "
            "post-quantum key transport). Mint a keypair: python -c \"from "
            "scrapyard.security.pq_field_encryption import generate_recipient_hex; "
            "print(generate_recipient_hex())\" and set PQ_FIELD_PUBLIC / PQ_FIELD_SECRET."
        )
    return bytes.fromhex(raw)


def _recipient_secrets() -> list[bytes]:
    raw = os.environ.get("PQ_FIELD_SECRET")
    if not raw:
        raise RuntimeError("PQ_FIELD_SECRET not set (needed to decrypt fields at rest).")
    return [bytes.fromhex(part.strip()) for part in raw.split(",") if part.strip()]


try:
    from sqlalchemy.types import TypeDecorator, Text as _Text

    class PQEncryptedString(TypeDecorator):
        """A SQLAlchemy column type that hybrid-PQ-encrypts on write and decrypts
        on read. Reads PQ_FIELD_PUBLIC / PQ_FIELD_SECRET at flush/load time.

        Usage:  mrn: Mapped[str] = mapped_column(PQEncryptedString(aad=b'patients.mrn'))
        The `aad` binds the value to its table.column (substitution resistance)."""
        impl = _Text
        cache_ok = True

        def __init__(self, *args, aad: bytes = b"", **kw):
            self._aad = aad if isinstance(aad, bytes) else str(aad).encode()
            super().__init__(*args, **kw)

        def process_bind_param(self, value, dialect):
            return pq_encrypt(value, _recipient_public(), aad=self._aad) if value is not None else None

        def process_result_value(self, value, dialect):
            return pq_decrypt(value, _recipient_secrets(), aad=self._aad) if value is not None else None
except Exception:  # sqlalchemy not installed at import time
    PQEncryptedString = None


def _selftest() -> None:
    """Offline, falsifiable self-test of hybrid-PQ field encryption. Skips
    gracefully if the post-quantum KEM library / cryptography is unavailable."""
    try:
        import cryptography  # noqa: F401
        from scrapyard.security.pq_envelope import _ml_kem
        _ml_kem()  # forces the lazy kyber_py import; raises if absent
    except Exception as e:
        print(f"pq_field_encryption: SKIPPED (post-quantum KEM lib unavailable: {type(e).__name__})")
        return

    pub, sec = generate_recipient()
    aad = b"patients.mrn"
    pt = "MRN-0009-XYZ"

    # 1) roundtrip: pq_decrypt(pq_encrypt(x)) == x
    tok = pq_encrypt(pt, pub, aad=aad)
    assert pq_decrypt(tok, [sec], aad=aad) == pt, "field value must round-trip"

    # 2) NEGATIVE: stored token (base64 wire) must not contain the plaintext
    assert pt not in tok, "stored ciphertext must not leak plaintext"

    # 3) NEGATIVE: wrong AAD (column substitution) must fail to decrypt
    bad_aad = False
    try:
        pq_decrypt(tok, [sec], aad=b"patients.ssn")
    except Exception:
        bad_aad = True
    assert bad_aad, "mismatched AAD must fail (substitution resistance)"

    # 4) NEGATIVE: a wrong/rotated-out key set fails closed with RuntimeError
    _, other = generate_recipient()
    wrong = False
    try:
        pq_decrypt(tok, [other], aad=aad)
    except RuntimeError:
        wrong = True
    assert wrong, "no valid key must raise RuntimeError (fail closed)"

    # 5) rotation: decrypt still works when the correct key is one of several tried
    assert pq_decrypt(tok, [other, sec], aad=aad) == pt, "rotation list must find the right key"

    # 6) hex keypair helper produces usable keys
    ph, sh = generate_recipient_hex()
    tok2 = pq_encrypt(pt, bytes.fromhex(ph), aad=aad)
    assert pq_decrypt(tok2, [bytes.fromhex(sh)], aad=aad) == pt, "hex keypair must work"

    print("pq_field_encryption: OK (6 assertions incl. wrong-AAD + wrong-key negatives)")


if __name__ == "__main__":
    _selftest()
