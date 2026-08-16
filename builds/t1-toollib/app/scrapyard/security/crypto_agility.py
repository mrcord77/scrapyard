"""
crypto_agility — Named cryptographic suites with backend selection and honest PQC tiering.

### PART-META-JSON
{
  "name": "crypto_agility",
  "layer": "security",
  "purpose": "Name every crypto operation as a swappable cipher suite and select the backend, so algorithms can migrate without rewrites.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Suite ids (str), policy hints ('require_pq'), env vars SCRAPYARD_CRYPTO_SUITE / SCRAPYARD_CRYPTO_BACKEND.",
  "outputs": "Suite descriptors, selected suite ids, backend names, and honest tier classifications (classical | pq-hybrid | pq-pure).",
  "files_created": [],
  "security_notes": "This part holds NO key material and performs NO crypto itself — it is the agility/policy layer that pq_envelope and pq_signing consult. The threat it addresses is harvest-now-decrypt-later: classical key transport/signatures are recorded so a future migration can find and re-wrap them. Default suites are hybrid PQC (classical + PQ), which stays secure if EITHER component holds. Never downgrade to a classical-only suite for a high-sensitivity domain without recording why. Stamp the suite id into stored data so ciphertext/signatures are self-describing and migratable.",
  "ai_usage": "Import suite ids and select_kem_suite/select_sig_suite from scrapyard.security.crypto_agility. pq_envelope and pq_signing call describe()/tier() to report what protection is actually in force; do not claim 'post-quantum' for a suite whose tier() is 'classical'.",
  "example": "from scrapyard.security.crypto_agility import select_kem_suite, describe; s = select_kem_suite(); print(describe(s)['tier'])",
  "import_path": "scrapyard.security.crypto_agility"
}
### END-PART-META
"""
from __future__ import annotations
import os

STATUS = "core"

# --- Suite identifiers (stamp these into stored ciphertext/signatures) --------
# KEM / envelope suites
KEM_HYBRID_MLKEM768_X25519 = "hybrid-mlkem768-x25519-aes256gcm"  # PQ + classical
KEM_CLASSICAL_X25519 = "classical-x25519-aes256gcm"               # classical only
# Signature suites
SIG_HYBRID_MLDSA65_ED25519 = "hybrid-mldsa65-ed25519"            # PQ + classical
SIG_CLASSICAL_ED25519 = "classical-ed25519"                       # classical only

# --- Suite registry -----------------------------------------------------------
# `pq`     : suite includes a NIST PQC primitive (resists Shor on key transport/signatures)
# `hybrid` : combines classical + PQ so it is secure if EITHER component holds
# `tier`   : honest label — never claim more than the suite delivers
SUITES: dict[str, dict] = {
    KEM_HYBRID_MLKEM768_X25519: {
        "family": "kem", "pq": True, "hybrid": True, "tier": "pq-hybrid",
        "kem_pq": "ML-KEM-768", "kem_classical": "X25519",
        "kdf": "HKDF-SHA256", "aead": "AES-256-GCM",
        "standards": ["FIPS 203"],
        "note": "Decryption requires BOTH the X25519 and ML-KEM secrets.",
    },
    KEM_CLASSICAL_X25519: {
        "family": "kem", "pq": False, "hybrid": False, "tier": "classical",
        "kem_pq": None, "kem_classical": "X25519",
        "kdf": "HKDF-SHA256", "aead": "AES-256-GCM",
        "standards": [],
        "note": "Quantum-vulnerable key transport (Shor). Recorded for later migration.",
    },
    SIG_HYBRID_MLDSA65_ED25519: {
        "family": "sig", "pq": True, "hybrid": True, "tier": "pq-hybrid",
        "sig_pq": "ML-DSA-65", "sig_classical": "Ed25519",
        "standards": ["FIPS 204"],
        "note": "Verification requires BOTH signatures to validate.",
    },
    SIG_CLASSICAL_ED25519: {
        "family": "sig", "pq": False, "hybrid": False, "tier": "classical",
        "sig_pq": None, "sig_classical": "Ed25519",
        "standards": [],
        "note": "Quantum-vulnerable signature (Shor). Recorded for later migration.",
    },
}

# Defaults: hybrid PQC is the floor. "Ahead of the times" = PQ on by default,
# classical only as an explicit, recorded downgrade.
DEFAULT_KEM_SUITE = KEM_HYBRID_MLKEM768_X25519
DEFAULT_SIG_SUITE = SIG_HYBRID_MLDSA65_ED25519

# Backends: 'local' = in-process primitives (pyca + pure-python ML-KEM/ML-DSA),
# 'citadel' = the Rust citadel keystore/envelope (sidecar API or FFI) — preferred
# in production for its DEK/KEK custody, replay protection, and audit witness.
KNOWN_BACKENDS = ("local", "citadel")


class SuiteError(ValueError):
    """Unknown or wrong-family suite id."""


def describe(suite_id: str) -> dict:
    """Return the suite descriptor (raises SuiteError if unknown)."""
    try:
        return dict(SUITES[suite_id], id=suite_id)
    except KeyError:
        raise SuiteError(f"unknown crypto suite: {suite_id!r}") from None


def tier(suite_id: str) -> str:
    """Honest protection tier: 'pq-hybrid' | 'pq-pure' | 'classical'."""
    return describe(suite_id)["tier"]


def is_post_quantum(suite_id: str) -> bool:
    """True iff the suite includes a NIST PQC primitive. Use this — not the
    string 'pq' in a name — before reporting post-quantum protection."""
    return bool(describe(suite_id)["pq"])


def _env_suite(family: str) -> str | None:
    """Allow an operator to pin a suite via SCRAPYARD_CRYPTO_SUITE, validated
    to the requested family. A wrong-family/unknown value fails loudly."""
    pinned = os.environ.get("SCRAPYARD_CRYPTO_SUITE")
    if not pinned:
        return None
    d = describe(pinned)  # raises on unknown
    if d["family"] != family:
        raise SuiteError(
            f"SCRAPYARD_CRYPTO_SUITE={pinned!r} is a {d['family']} suite, "
            f"not a {family} suite"
        )
    return pinned


def select_kem_suite(require_pq: bool = True) -> str:
    """Pick the KEM/envelope suite. Defaults to hybrid PQC. An operator override
    (SCRAPYARD_CRYPTO_SUITE) is honored unless it would drop PQ while require_pq."""
    pinned = _env_suite("kem")
    if pinned:
        if require_pq and not is_post_quantum(pinned):
            raise SuiteError(
                f"policy requires post-quantum key transport but "
                f"SCRAPYARD_CRYPTO_SUITE={pinned!r} is classical-only"
            )
        return pinned
    return DEFAULT_KEM_SUITE


def select_sig_suite(require_pq: bool = True) -> str:
    """Pick the signature suite. Defaults to hybrid PQC; same override rules."""
    pinned = _env_suite("sig")
    if pinned:
        if require_pq and not is_post_quantum(pinned):
            raise SuiteError(
                f"policy requires post-quantum signatures but "
                f"SCRAPYARD_CRYPTO_SUITE={pinned!r} is classical-only"
            )
        return pinned
    return DEFAULT_SIG_SUITE


class BackendNotConfigured(SuiteError):
    """A real backend was selected but its required configuration is absent. This is
    a configuration error to fix (not an unimplemented feature) — set the citadel env
    or choose SCRAPYARD_CRYPTO_BACKEND=local."""


def citadel_configured() -> bool:
    """True when the citadel backend has what it needs: an in-process FFI library
    (CITADEL_LIB) or the sidecar API (CITADEL_URL + CITADEL_KEY)."""
    return bool(os.environ.get("CITADEL_LIB")
                or (os.environ.get("CITADEL_URL") and os.environ.get("CITADEL_KEY")))


def select_backend() -> str:
    """Resolve the crypto backend: SCRAPYARD_CRYPTO_BACKEND or 'local'.
    'citadel' routes envelope/signing to the Rust citadel service (sidecar/FFI);
    'local' uses in-process primitives so smoke/runtime verification needs no
    external service. Unknown values fail loudly; selecting citadel without its
    configuration fails fast (crypto must never silently downgrade backends)."""
    b = os.environ.get("SCRAPYARD_CRYPTO_BACKEND", "local").strip().lower()
    if b not in KNOWN_BACKENDS:
        raise SuiteError(f"unknown crypto backend {b!r}; known: {KNOWN_BACKENDS}")
    if b == "citadel" and not citadel_configured():
        raise BackendNotConfigured(
            "SCRAPYARD_CRYPTO_BACKEND=citadel but citadel is not configured. Set "
            "CITADEL_LIB (in-process FFI to libcitadel) or CITADEL_URL+CITADEL_KEY "
            "(citadel-api sidecar), or use SCRAPYARD_CRYPTO_BACKEND=local. The local "
            "backend is a correct FIPS 203/204 reference (not constant-time/audited); "
            "citadel is the audited Rust production backend with an identical wire format."
        )
    return b


def policy_report(require_pq: bool = True) -> dict:
    """Machine-readable summary of the crypto posture currently in force — what
    confidence/maturity reporting should consume instead of asserting 'PQC'."""
    kem, sig = select_kem_suite(require_pq), select_sig_suite(require_pq)
    return {
        "backend": select_backend(),
        "kem_suite": kem, "kem_tier": tier(kem), "kem_pq": is_post_quantum(kem),
        "sig_suite": sig, "sig_tier": tier(sig), "sig_pq": is_post_quantum(sig),
        "post_quantum": is_post_quantum(kem) and is_post_quantum(sig),
    }


def _selftest() -> None:
    """Offline, falsifiable self-test of the crypto-agility registry, negotiation
    and policy layer. No key material, no network — pure suite/policy logic.

    Hermetic: saves and restores every SCRAPYARD_/CITADEL_ env var it touches so
    the process environment is unchanged on exit.
    """
    guarded = ("SCRAPYARD_CRYPTO_SUITE", "SCRAPYARD_CRYPTO_BACKEND",
               "CITADEL_LIB", "CITADEL_URL", "CITADEL_KEY")
    saved = {k: os.environ.get(k) for k in guarded}
    for k in guarded:
        os.environ.pop(k, None)
    try:
        # 1) Registry describe(): a known hybrid KEM is PQ + hybrid, tier is honest.
        d = describe(KEM_HYBRID_MLKEM768_X25519)
        assert d["pq"] is True and d["hybrid"] is True and d["tier"] == "pq-hybrid"
        assert d["id"] == KEM_HYBRID_MLKEM768_X25519
        assert is_post_quantum(KEM_HYBRID_MLKEM768_X25519) is True

        # 2) Honest tiering: the classical suite must NOT be reported as post-quantum.
        assert tier(KEM_CLASSICAL_X25519) == "classical"
        assert is_post_quantum(KEM_CLASSICAL_X25519) is False

        # 3) NEGATIVE: an unknown/deprecated algorithm id is rejected, not guessed.
        try:
            describe("rot13-broken-suite")
            raise AssertionError("unknown suite must raise SuiteError")
        except SuiteError:
            pass

        # 4) Default negotiation lands on hybrid PQC for both families.
        assert select_kem_suite() == DEFAULT_KEM_SUITE
        assert select_sig_suite() == DEFAULT_SIG_SUITE
        assert is_post_quantum(select_kem_suite()) and is_post_quantum(select_sig_suite())

        # 5) Operator override via env is honored when it stays PQ.
        os.environ["SCRAPYARD_CRYPTO_SUITE"] = KEM_HYBRID_MLKEM768_X25519
        assert select_kem_suite(require_pq=True) == KEM_HYBRID_MLKEM768_X25519

        # 6) NEGATIVE: policy requires PQ but the pinned suite is classical -> refused.
        os.environ["SCRAPYARD_CRYPTO_SUITE"] = KEM_CLASSICAL_X25519
        try:
            select_kem_suite(require_pq=True)
            raise AssertionError("classical-only suite must be refused under require_pq")
        except SuiteError:
            pass
        # ...but the same classical suite is allowed as an explicit, recorded downgrade.
        assert select_kem_suite(require_pq=False) == KEM_CLASSICAL_X25519

        # 7) NEGATIVE: a signature-family override cannot satisfy a KEM request.
        os.environ["SCRAPYARD_CRYPTO_SUITE"] = SIG_HYBRID_MLDSA65_ED25519
        try:
            select_kem_suite(require_pq=False)
            raise AssertionError("wrong-family suite pin must be rejected")
        except SuiteError:
            pass
        os.environ.pop("SCRAPYARD_CRYPTO_SUITE", None)

        # 8) Backend selection: default is 'local'; unknown backend fails loudly.
        assert select_backend() == "local"
        os.environ["SCRAPYARD_CRYPTO_BACKEND"] = "quantum-teleporter"
        try:
            select_backend()
            raise AssertionError("unknown backend must raise SuiteError")
        except SuiteError:
            pass
        # 9) NEGATIVE: selecting citadel without its config fails fast (no silent downgrade).
        os.environ["SCRAPYARD_CRYPTO_BACKEND"] = "citadel"
        assert citadel_configured() is False
        try:
            select_backend()
            raise AssertionError("citadel without config must raise BackendNotConfigured")
        except BackendNotConfigured:
            pass
        os.environ.pop("SCRAPYARD_CRYPTO_BACKEND", None)

        # 10) policy_report reflects the posture honestly (all-PQ default).
        rep = policy_report(require_pq=True)
        assert rep["backend"] == "local" and rep["post_quantum"] is True
        assert rep["kem_tier"] == "pq-hybrid" and rep["sig_tier"] == "pq-hybrid"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print("crypto_agility selftest OK (10 checks incl. unknown-suite / "
          "classical-under-require_pq / wrong-family / unconfigured-citadel negatives)")


if __name__ == "__main__":
    _selftest()
