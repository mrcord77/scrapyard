"""
pq_signing — Hybrid post-quantum digital signatures (Ed25519 + ML-DSA-65).

### PART-META-JSON
{
  "name": "pq_signing",
  "layer": "security",
  "purpose": "Sign and verify with hybrid post-quantum signatures for tamper-evident audit witness and attestation, valid only if both Ed25519 and ML-DSA-65 verify.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "cryptography",
    "dilithium-py"
  ],
  "inputs": "A signing keypair (Ed25519 + ML-DSA-65), and message bytes (or an audit-entry dict to witness).",
  "outputs": "A self-describing signature blob carrying the suite id and both signatures; verify() returns True only when BOTH components validate.",
  "files_created": [],
  "security_notes": "Hybrid AND-composition: verify() requires the Ed25519 AND the ML-DSA-65 signature to validate, so forgery needs breaking both. Use this where YOU control the verifier — audit-log witnessing, build/artifact attestation, internal service tokens — NOT for JWTs handed to external relying parties, where PQC in JOSE is not yet standardized or widely verifiable and the ~3.3KB ML-DSA signature breaks interop. The 'local' backend's pure-python ML-DSA is a correct FIPS 204 reference implementation, not constant-time or independently audited; production should use the citadel signer (Rust ML-DSA-65) via SCRAPYARD_CRYPTO_BACKEND=citadel. Audit witnessing is tamper-EVIDENT, not tamper-PROOF: store signatures append-only and verify on read. Never log the secret key.",
  "ai_usage": "generate_keypair() once; keep the secret in a secrets manager or citadel custody and publish the public key to verifiers. sign/verify for raw bytes; witness(entry)/verify_witness(record, public) to make audit-log rows tamper-evident. Pair with scrapyard.security.crypto_agility for suite selection and honest tier reporting.",
  "example": "from scrapyard.security.pq_signing import generate_keypair, sign, verify; pk, sk = generate_keypair(); s = sign(sk, b'event'); assert verify(pk, b'event', s)",
  "import_path": "scrapyard.security.pq_signing"
}
### END-PART-META
"""
from __future__ import annotations
import json
import struct

STATUS = "core"


def _ml_dsa():
    """FIPS 204 ML-DSA-65. Lazy import; citadel supplies the production primitive."""
    from dilithium_py.ml_dsa import ML_DSA_65
    return ML_DSA_65


def _join(a: bytes, b: bytes) -> bytes:
    return struct.pack(">I", len(a)) + a + b


def _split(blob: bytes) -> tuple[bytes, bytes]:
    (n,) = struct.unpack(">I", blob[:4])
    return blob[4:4 + n], blob[4 + n:]


def generate_keypair() -> tuple[bytes, bytes]:
    """Mint a hybrid signing keypair.

    Returns (public, secret) as length-prefixed blobs:
      public = Ed25519 public (32B) + ML-DSA-65 public
      secret = Ed25519 private (32B) + ML-DSA-65 secret
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    ed_sk = Ed25519PrivateKey.generate()
    ed_sk_b = ed_sk.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    ed_pk_b = ed_sk.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    pq_pk, pq_sk = _ml_dsa().keygen()
    return _join(ed_pk_b, bytes(pq_pk)), _join(ed_sk_b, bytes(pq_sk))


def sign(secret: bytes, message: bytes, suite_id: str | None = None) -> bytes:
    """Produce a hybrid signature blob over `message`."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from scrapyard.security import crypto_agility as CA

    suite_id = suite_id or CA.select_sig_suite()
    d = CA.describe(suite_id)
    if d["family"] != "sig":
        raise CA.SuiteError(f"{suite_id!r} is not a signature suite")
    if CA.select_backend() == "citadel":
        return _citadel_sign(secret, message, suite_id)

    ed_sk_b, pq_sk = _split(secret)
    ed_sig = Ed25519PrivateKey.from_private_bytes(ed_sk_b).sign(message)
    pq_sig = bytes(_ml_dsa().sign(pq_sk, message)) if d["pq"] else b""
    return _encode(suite_id, ed_sig, pq_sig)


def verify(public: bytes, message: bytes, signature: bytes,
           expected_suite: str | None = None) -> bool:
    """Verify a hybrid signature. Returns True only if BOTH the Ed25519 and the
    ML-DSA-65 signatures validate (AND-composition). Any failure -> False.

    The PQ requirement is enforced from the KEY (and optional policy), NOT from
    the container's self-declared suite id, which is unsigned and
    attacker-controlled. If the public key is hybrid (carries an ML-DSA-65
    component), a signature that drops the PQ part is REJECTED regardless of the
    suite id stamped into the blob — this closes the post-quantum downgrade
    attack. Pass ``expected_suite`` to additionally pin the accepted suite and
    reject any container that claims a different (weaker) one.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    from scrapyard.security import crypto_agility as CA

    try:
        suite_id, ed_sig, pq_sig = _decode(signature)
        # Policy pin (defense-in-depth): reject any container that self-declares
        # a suite other than the one the caller/policy expects.
        if expected_suite is not None and suite_id != expected_suite:
            return False
        d = CA.describe(suite_id)
        if CA.select_backend() == "citadel":
            return _citadel_verify(public, message, signature, suite_id)
        ed_pk_b, pq_pk = _split(public)
        # A hybrid public key (non-empty ML-DSA component) REQUIRES a PQ
        # signature — the container cannot opt out by claiming a classical suite.
        require_pq = bool(pq_pk) or bool(d["pq"])
        try:
            Ed25519PublicKey.from_public_bytes(ed_pk_b).verify(ed_sig, message)
        except InvalidSignature:
            return False
        if require_pq:
            if not pq_sig:
                return False
            if not _ml_dsa().verify(pq_pk, message, pq_sig):
                return False
        return True
    except Exception:
        return False


# --- audit witness (tamper-evident audit rows) --------------------------------
def witness(entry: dict, secret: bytes) -> dict:
    """Return a copy of an audit entry with a hybrid signature over its canonical
    JSON. Store the result append-only; verify on read to detect tampering."""
    payload = _canonical(entry)
    sig = sign(secret, payload)
    out = dict(entry)
    out["_witness"] = sig.hex()
    return out


def verify_witness(record: dict, public: bytes) -> bool:
    """Verify a record produced by witness() — recomputes the canonical payload
    over everything except the witness field and checks the hybrid signature."""
    rec = dict(record)
    sig_hex = rec.pop("_witness", None)
    if not sig_hex:
        return False
    return verify(public, _canonical(rec), bytes.fromhex(sig_hex))


def _canonical(entry: dict) -> bytes:
    """Stable serialization so witness/verify agree regardless of key order."""
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str).encode()


# --- signature blob format (self-describing; embeds suite id) -----------------
def _encode(suite_id: str, ed_sig: bytes, pq_sig: bytes) -> bytes:
    sid = suite_id.encode()
    return b"".join([
        struct.pack(">B", len(sid)), sid,
        struct.pack(">H", len(ed_sig)), ed_sig,
        struct.pack(">I", len(pq_sig)), pq_sig,
    ])


def _decode(blob: bytes) -> tuple[str, bytes, bytes]:
    i = 0
    (sl,) = struct.unpack(">B", blob[i:i + 1]); i += 1
    suite_id = blob[i:i + sl].decode(); i += sl
    (el,) = struct.unpack(">H", blob[i:i + 2]); i += 2
    ed_sig = blob[i:i + el]; i += el
    (pl,) = struct.unpack(">I", blob[i:i + 4]); i += 4
    pq_sig = blob[i:i + pl]
    return suite_id, ed_sig, pq_sig


def suite_of(signature: bytes) -> str:
    """Read the suite id stamped into a stored signature (for migration/inventory)."""
    return _decode(signature)[0]


# --- citadel backend hook -----------------------------------------------------
def _citadel():
    from scrapyard.security.crypto_agility import BackendNotConfigured
    raise BackendNotConfigured(
        "citadel signer selected (SCRAPYARD_CRYPTO_BACKEND=citadel) but not configured. "
        "Set CITADEL_LIB / CITADEL_URL+CITADEL_KEY, or use SCRAPYARD_CRYPTO_BACKEND=local. "
        "citadel signs with the same ML-DSA-65 parameter set, so signatures interoperate."
    )


def _citadel_sign(secret, message, suite_id):  # pragma: no cover - needs service
    _citadel()


def _citadel_verify(public, message, signature, suite_id):  # pragma: no cover
    _citadel()


def _selftest() -> None:
    """Offline, falsifiable self-test of the hybrid PQ signature. Skips gracefully
    if the post-quantum signature library (dilithium-py) or cryptography is absent."""
    try:
        import cryptography  # noqa: F401
        _ml_dsa()  # forces the lazy dilithium_py import; raises if absent
    except Exception as e:
        print(f"pq_signing: SKIPPED (post-quantum signature lib unavailable: {type(e).__name__})")
        return

    pub, sec = generate_keypair()
    msg = b"audit-row: user=7 action=export ts=1700000000"

    # 1) a genuine signature verifies
    sig = sign(sec, msg)
    assert verify(pub, msg, sig) is True, "genuine signature must verify"

    # 2) NEGATIVE: a modified message must NOT verify (tamper-evidence)
    assert verify(pub, msg + b"!", sig) is False, "altered message must fail verification"

    # 3) NEGATIVE: a different public key must NOT verify
    other_pub, _ = generate_keypair()
    assert verify(other_pub, msg, sig) is False, "wrong public key must fail"

    # 4) NEGATIVE: a corrupted signature blob must NOT verify (and must not raise)
    corrupt = bytearray(sig); corrupt[-1] ^= 0xFF
    assert verify(pub, msg, bytes(corrupt)) is False, "corrupted signature must fail closed"

    # 5) the signature self-describes a post-quantum suite
    from scrapyard.security import crypto_agility as CA
    assert CA.is_post_quantum(suite_of(sig)), "default signature suite must be post-quantum"

    # 5b) EXPLOIT REGRESSION: post-quantum DOWNGRADE attack. Decode a genuine
    # hybrid signature, keep its valid Ed25519 component, drop the ML-DSA part
    # and re-stamp the (unsigned) suite id to classical-ed25519. verify() must
    # NOT trust the container's self-declared suite: the hybrid KEY still
    # requires the PQ component, so the downgraded blob fails closed.
    suite_id, ed_sig, pq_sig = _decode(sig)
    assert CA.is_post_quantum(suite_id), "test precondition: original is hybrid"
    downgraded = _encode(CA.SIG_CLASSICAL_ED25519, ed_sig, b"")
    assert suite_of(downgraded) == CA.SIG_CLASSICAL_ED25519, "test built a classical container"
    assert verify(pub, msg, downgraded) is False, \
        "PQ downgrade (classical-only re-stamp of a hybrid key) must NOT verify"
    # A classical suite id with a bogus non-empty PQ blob is also rejected.
    downgraded_fakepq = _encode(CA.SIG_CLASSICAL_ED25519, ed_sig, b"\x00" * 8)
    assert verify(pub, msg, downgraded_fakepq) is False, \
        "re-stamped suite with garbage PQ signature must NOT verify"
    # Single-component tampering still fails: corrupt only the PQ signature.
    corrupt_pq = bytearray(pq_sig); corrupt_pq[0] ^= 0xFF
    only_pq_bad = _encode(suite_id, ed_sig, bytes(corrupt_pq))
    assert verify(pub, msg, only_pq_bad) is False, "invalid PQ component must fail the AND-composition"
    # ...and corrupt only the Ed25519 signature.
    corrupt_ed = bytearray(ed_sig); corrupt_ed[0] ^= 0xFF
    only_ed_bad = _encode(suite_id, bytes(corrupt_ed), pq_sig)
    assert verify(pub, msg, only_ed_bad) is False, "invalid Ed25519 component must fail the AND-composition"
    # Policy pin: an expected_suite mismatch is rejected even for a valid blob.
    assert verify(pub, msg, sig, expected_suite=CA.SIG_HYBRID_MLDSA65_ED25519) is True, \
        "matching expected_suite must still verify"
    assert verify(pub, msg, sig, expected_suite=CA.SIG_CLASSICAL_ED25519) is False, \
        "expected_suite mismatch must be rejected"

    # 6) audit witness round-trips, and tampering with a witnessed row is detected
    entry = {"user": 7, "action": "export", "rows": 42}
    rec = witness(entry, sec)
    assert verify_witness(rec, pub) is True, "witnessed record must verify"
    tampered = dict(rec); tampered["rows"] = 43
    assert verify_witness(tampered, pub) is False, "tampered witnessed record must be detected"

    print("pq_signing: OK (7 assertions incl. tamper + wrong-key + witness-tamper negatives)")


if __name__ == "__main__":
    _selftest()
