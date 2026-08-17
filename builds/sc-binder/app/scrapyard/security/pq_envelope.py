"""
pq_envelope — Hybrid post-quantum envelope encryption (X25519 + ML-KEM-768 -> AES-256-GCM).

### PART-META-JSON
{
  "name": "pq_envelope",
  "layer": "security",
  "purpose": "Seal data and wrap data-encryption keys with hybrid post-quantum key transport, secure if either X25519 or ML-KEM-768 holds.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "cryptography",
    "kyber-py"
  ],
  "inputs": "Recipient public key (X25519 pk + ML-KEM-768 ek), plaintext/DEK bytes, and AAD bytes that bind the ciphertext to its context (table/row/field).",
  "outputs": "Self-describing wire bytes carrying the suite id, X25519 ephemeral pubkey, ML-KEM ciphertext, AEAD nonce, and AES-256-GCM ciphertext+tag; open() returns the plaintext only when BOTH recipient secrets are present.",
  "files_created": [],
  "security_notes": "Hybrid by construction: the AEAD key is HKDF(X25519_shared || ML-KEM_shared), so decryption requires BOTH recipient secrets — it stays secure against a quantum attacker who breaks X25519 (Shor) as long as ML-KEM-768 holds, and against a flaw in ML-KEM as long as X25519 holds. AAD MUST bind context (e.g. table/row/field) to stop ciphertext substitution; open() rejects mismatched AAD. The 'local' backend's pure-python ML-KEM is a correct FIPS 203 reference implementation, not constant-time or independently audited — for production use the citadel backend (SCRAPYARD_CRYPTO_BACKEND=citadel), whose Rust ML-KEM-768 carries the DEK/KEK custody, replay protection, and audit witness. Each envelope embeds its suite id so stored ciphertext is migratable. Never log the recipient secret key or derived AEAD key.",
  "ai_usage": "generate_recipient() once and store the secret securely (or let citadel custody it). seal(pt, recipient_pub, aad)/open(wire, recipient_secret, aad) for direct sealing; wrap_dek/unwrap_dek for the envelope-of-DEK pattern that field/record encryption should use. Pair with scrapyard.security.crypto_agility for suite/backend selection and honest tier reporting.",
  "example": "from scrapyard.security.pq_envelope import generate_recipient, seal, open as pq_open; pk, sk = generate_recipient(); w = seal(b'secret', pk, aad=b'patients:1:mrn'); assert pq_open(w, sk, aad=b'patients:1:mrn') == b'secret'",
  "import_path": "scrapyard.security.pq_envelope"
}
### END-PART-META
"""
from __future__ import annotations
import os
import struct

STATUS = "core"

_MAGIC = b"PQE1"
_NONCE_LEN = 12
_DEK_LEN = 32  # AES-256


# --- ML-KEM-768 primitive (local backend) -------------------------------------
def _ml_kem():
    """FIPS 203 ML-KEM-768. Imported lazily so importing this part never forces
    the dependency. kyber-py is a correct reference implementation; the citadel
    backend supplies the production (Rust) primitive."""
    from kyber_py.ml_kem import ML_KEM_768
    return ML_KEM_768


# --- recipient keypair --------------------------------------------------------
def generate_recipient() -> tuple[bytes, bytes]:
    """Mint a hybrid recipient keypair.

    Returns (public, secret) as self-describing length-prefixed byte blobs:
      public = X25519 public key (32B) + ML-KEM-768 encapsulation key
      secret = X25519 private key (32B) + ML-KEM-768 decapsulation key
    Store `secret` in a secrets manager or hand custody to citadel; never commit it.
    """
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    x_sk = X25519PrivateKey.generate()
    x_sk_b = x_sk.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    x_pk_b = x_sk.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    ek, dk = _ml_kem().keygen()
    public = _join(x_pk_b, bytes(ek))
    secret = _join(x_sk_b, bytes(dk))
    return public, secret


def _join(a: bytes, b: bytes) -> bytes:
    return struct.pack(">I", len(a)) + a + b


def _split(blob: bytes) -> tuple[bytes, bytes]:
    (n,) = struct.unpack(">I", blob[:4])
    return blob[4:4 + n], blob[4 + n:]


# --- key derivation -----------------------------------------------------------
def _derive_key(shared_x: bytes, shared_pq: bytes, suite_id: str, aad: bytes) -> bytes:
    """HKDF-SHA256 over the concatenation of both shared secrets. Mixing both is
    what makes the construction hybrid: an attacker must recover BOTH to derive
    the key. The suite id is the salt; AAD is folded into info for domain binding."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_DEK_LEN,
        salt=suite_id.encode(),
        info=b"pq_envelope/v1|" + aad,
    )
    return hkdf.derive(shared_x + shared_pq)


# --- seal / open --------------------------------------------------------------
def seal(plaintext: bytes, recipient_public: bytes, aad: bytes = b"",
         suite_id: str | None = None) -> bytes:
    """Encrypt `plaintext` to `recipient_public` under a hybrid suite. `aad`
    binds the ciphertext to its context and is authenticated (not encrypted)."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey, X25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from scrapyard.security import crypto_agility as CA

    suite_id = suite_id or CA.select_kem_suite()
    d = CA.describe(suite_id)
    if d["family"] != "kem":
        raise CA.SuiteError(f"{suite_id!r} is not a KEM suite")
    if CA.select_backend() == "citadel":
        return _citadel_seal(plaintext, recipient_public, aad, suite_id)

    x_pk_b, ek = _split(recipient_public)

    # classical share: ephemeral X25519 ECDH
    eph = X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    shared_x = eph.exchange(X25519PublicKey.from_public_bytes(x_pk_b))

    # post-quantum share: ML-KEM-768 encapsulation (skipped only for classical suite)
    if d["pq"]:
        shared_pq, kem_ct = _ml_kem().encaps(ek)
        shared_pq, kem_ct = bytes(shared_pq), bytes(kem_ct)
    else:
        shared_pq, kem_ct = b"", b""

    key = _derive_key(shared_x, shared_pq, suite_id, aad)
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad)
    return _encode(suite_id, eph_pub, kem_ct, nonce, ct)


def open(wire: bytes, recipient_secret: bytes, aad: bytes = b"") -> bytes:
    """Decrypt a wire produced by seal(). Requires BOTH recipient secrets; an
    AAD that differs from sealing time raises (authenticated, not silently wrong)."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey, X25519PublicKey,
    )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from scrapyard.security import crypto_agility as CA

    suite_id, eph_pub, kem_ct, nonce, ct = _decode(wire)
    d = CA.describe(suite_id)
    if CA.select_backend() == "citadel":
        return _citadel_open(wire, recipient_secret, aad, suite_id)

    x_sk_b, dk = _split(recipient_secret)
    shared_x = X25519PrivateKey.from_private_bytes(x_sk_b).exchange(
        X25519PublicKey.from_public_bytes(eph_pub)
    )
    shared_pq = bytes(_ml_kem().decaps(dk, kem_ct)) if d["pq"] else b""
    key = _derive_key(shared_x, shared_pq, suite_id, aad)
    return AESGCM(key).decrypt(nonce, ct, aad)


# --- DEK wrapping (envelope-of-DEK pattern for field/record encryption) -------
def new_dek() -> bytes:
    """A fresh 256-bit data-encryption key for bulk AES-256-GCM."""
    return os.urandom(_DEK_LEN)


def wrap_dek(dek: bytes, recipient_public: bytes, aad: bytes = b"") -> bytes:
    """Wrap a DEK for storage alongside ciphertext (encrypt the small key with
    the hybrid envelope; encrypt the bulk data separately with the DEK)."""
    if len(dek) != _DEK_LEN:
        raise ValueError(f"DEK must be {_DEK_LEN} bytes")
    return seal(dek, recipient_public, aad)


def unwrap_dek(wrapped: bytes, recipient_secret: bytes, aad: bytes = b"") -> bytes:
    """Recover a DEK wrapped by wrap_dek()."""
    return open(wrapped, recipient_secret, aad)


# --- wire format (self-describing; embeds suite id) ---------------------------
def _encode(suite_id: str, eph_pub: bytes, kem_ct: bytes, nonce: bytes, ct: bytes) -> bytes:
    sid = suite_id.encode()
    return b"".join([
        _MAGIC,
        struct.pack(">B", len(sid)), sid,
        struct.pack(">H", len(eph_pub)), eph_pub,
        struct.pack(">I", len(kem_ct)), kem_ct,
        struct.pack(">B", len(nonce)), nonce,
        ct,
    ])


def _decode(wire: bytes) -> tuple[str, bytes, bytes, bytes, bytes]:
    if wire[:4] != _MAGIC:
        raise ValueError("not a pq_envelope wire (bad magic)")
    i = 4
    (sl,) = struct.unpack(">B", wire[i:i + 1]); i += 1
    suite_id = wire[i:i + sl].decode(); i += sl
    (el,) = struct.unpack(">H", wire[i:i + 2]); i += 2
    eph_pub = wire[i:i + el]; i += el
    (kl,) = struct.unpack(">I", wire[i:i + 4]); i += 4
    kem_ct = wire[i:i + kl]; i += kl
    (nl,) = struct.unpack(">B", wire[i:i + 1]); i += 1
    nonce = wire[i:i + nl]; i += nl
    ct = wire[i:]
    return suite_id, eph_pub, kem_ct, nonce, ct


def suite_of(wire: bytes) -> str:
    """Read the suite id stamped into a stored wire (for migration/inventory)."""
    return _decode(wire)[0]


# --- citadel backend hook -----------------------------------------------------
def _citadel():
    """Resolve the citadel backend (Rust): FFI cdylib if CITADEL_LIB points at
    libcitadel, else the citadel-api sidecar via CITADEL_URL/CITADEL_KEY. Kept
    behind selection so the default 'local' backend boots with no service."""
    from scrapyard.security.crypto_agility import BackendNotConfigured
    raise BackendNotConfigured(
        "citadel envelope selected (SCRAPYARD_CRYPTO_BACKEND=citadel) but not "
        "configured. Set CITADEL_LIB for in-process FFI, or CITADEL_URL/CITADEL_KEY "
        "for the citadel-api sidecar, or use SCRAPYARD_CRYPTO_BACKEND=local. The wire "
        "format is identical (X25519 + ML-KEM-768 + AES-256-GCM), so envelopes interoperate."
    )


def _citadel_seal(pt, pub, aad, suite_id):  # pragma: no cover - needs service
    _citadel()


def _citadel_open(wire, sk, aad, suite_id):  # pragma: no cover - needs service
    _citadel()


def _selftest() -> None:
    """Offline, falsifiable self-test of the hybrid PQ envelope. Skips gracefully
    if the post-quantum KEM library (kyber-py) or cryptography is not installed."""
    try:
        import cryptography  # noqa: F401
        _ml_kem()  # forces the lazy kyber_py import; raises if absent
    except Exception as e:
        print(f"pq_envelope: SKIPPED (post-quantum KEM lib unavailable: {type(e).__name__})")
        return

    pub, sec = generate_recipient()
    aad = b"patients:1:mrn"
    pt = b"harvest-now-decrypt-later target"

    # 1) roundtrip: open(seal(x)) == x under matching AAD
    wire = seal(pt, pub, aad=aad)
    assert open(wire, sec, aad=aad) == pt, "hybrid envelope must round-trip"

    # 2) NEGATIVE: ciphertext must not contain the plaintext
    assert pt not in wire, "sealed wire must not leak plaintext"

    # 3) NEGATIVE: a DIFFERENT AAD must fail (context binding / substitution resistance)
    bad_aad = False
    try:
        open(wire, sec, aad=b"patients:2:mrn")
    except Exception:
        bad_aad = True
    assert bad_aad, "mismatched AAD must fail to open"

    # 4) NEGATIVE: a DIFFERENT recipient secret must fail (needs both KEM shares)
    _, other_sec = generate_recipient()
    wrong_key = False
    try:
        open(wire, other_sec, aad=aad)
    except Exception:
        wrong_key = True
    assert wrong_key, "wrong recipient secret must fail to open"

    # 5) the wire self-describes a post-quantum hybrid suite
    from scrapyard.security import crypto_agility as CA
    sid = suite_of(wire)
    assert CA.is_post_quantum(sid), "default suite must be post-quantum"

    # 6) DEK wrap/unwrap round-trips
    dek = new_dek()
    assert unwrap_dek(wrap_dek(dek, pub, aad=aad), sec, aad=aad) == dek, "DEK wrap must round-trip"

    print("pq_envelope: OK (6 assertions incl. wrong-AAD + wrong-key negatives)")


if __name__ == "__main__":
    _selftest()
