"""
virus_scanning — Scan uploads via ClamAV/provider before persist.

### PART-META-JSON
{
  "name": "virus_scanning",
  "layer": "files",
  "purpose": "Scan uploads via ClamAV/provider before persist.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: set_scanner(fn); scan(data); assert_clean(data).",
  "outputs": "Returns: scan -> dict; assert_clean -> None.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `set_scanner` from `scrapyard.files.virus_scanning` and call it as shown in `example`; run `py -m scrapyard.files.virus_scanning` to see its offline selftest.",
  "example": "from scrapyard.files.virus_scanning import set_scanner",
  "import_path": "scrapyard.files.virus_scanning"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"

# EICAR test-string detection + a pluggable scanner hook. Real deployments wire
# ClamAV via scan_hook; the default catches the standard AV test signature and
# obviously-executable magic bytes so the upload path is enforceable in tests.
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR"

_scan_hook = None
def set_scanner(fn):
    global _scan_hook
    _scan_hook = fn

def scan(data: bytes) -> dict:
    if _scan_hook:
        return _scan_hook(data)
    if EICAR in data:
        return {"clean": False, "threat": "EICAR-Test-Signature"}
    if data[:2] == b"MZ" or data[:4] == b"\x7fELF":
        return {"clean": False, "threat": "executable-binary"}
    return {"clean": True, "threat": None}

def assert_clean(data: bytes) -> None:
    r = scan(data)
    if not r["clean"]:
        raise ValueError(f"upload rejected: {r['threat']}")


def _selftest() -> None:
    """Offline self-test: the standard EICAR anti-virus test signature is flagged,
    a clean payload passes, executable magic bytes are flagged, and a pluggable
    scanner hook overrides the default.

    The full EICAR string is assembled at runtime from the module's detection
    prefix plus a suffix built by concatenation, so the complete literal never
    appears in this source file (which would otherwise trip real host AV).
    """
    # Full standard EICAR string, assembled so no complete literal is stored on disk.
    eicar_full = EICAR + b"-STANDARD-" + b"ANTIVIRUS-" + b"TEST-FILE!" + b"$H+H*"

    # The EICAR test signature is detected as a threat.
    r = scan(eicar_full)
    assert r["clean"] is False and r["threat"] == "EICAR-Test-Signature", r

    # A benign payload passes cleanly.
    clean = scan(b"just some harmless user text \xe2\x9c\x93")
    assert clean["clean"] is True and clean["threat"] is None, clean

    # Executable magic bytes (PE 'MZ', ELF) are flagged.
    assert scan(b"MZ\x90\x00rest-of-a-pe")["clean"] is False
    assert scan(b"\x7fELF\x02\x01\x01")["threat"] == "executable-binary"

    # assert_clean raises on a threat and passes silently on clean data.
    try:
        assert_clean(eicar_full)
        raise AssertionError("assert_clean did not reject the EICAR signature")
    except ValueError:
        pass
    assert_clean(b"safe bytes")  # must not raise

    # Negative/adversarial: a pluggable hook overrides the default verdict (a real
    # deployment wiring ClamAV). Verify it is honored, then removed.
    set_scanner(lambda data: {"clean": False, "threat": "hook-forced"})
    try:
        assert scan(b"anything")["threat"] == "hook-forced", "custom scanner hook not applied"
    finally:
        set_scanner(None)
    assert scan(b"anything")["clean"] is True, "hook not cleared"

    print("virus_scanning selftest: PASS")


if __name__ == "__main__":
    _selftest()
