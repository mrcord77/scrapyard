"""
signed_urls — Time-limited HMAC-signed download/upload URLs.

### PART-META-JSON
{
  "name": "signed_urls",
  "layer": "files",
  "purpose": "Time-limited HMAC-SHA256 signed URLs (plain and policy-carrying) with a single canonical signing payload, plus audit records and policy validation.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Object key, shared secret, expiry seconds, optional JSON policy dict.",
  "outputs": "Signed URL strings; verification tuples (ok, key, exp); audit record dicts.",
  "files_created": [],
  "security_notes": "Signatures are HMAC-SHA256 over the canonical payload 'key:exp[:policy_b64]' and compared with hmac.compare_digest (constant-time). Both generation and verification use the SAME payload, so URLs verify. Expired URLs always fail. The secret never appears in URLs, logs, or audit records.",
  "ai_usage": "url = generate_signed_url(key, secret); ok, key, exp = verify_signed_url(url, secret). Policy flow: sign_with_policy(key, secret, {'methods': ['GET']}); verify_with_policy(url, secret).",
  "example": "from scrapyard.files.signed_urls import generate_signed_url, verify_signed_url",
  "import_path": "scrapyard.files.signed_urls"
}
### END-PART-META
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs, quote

STATUS = "core"
log = logging.getLogger("scrapyard.files.signed_urls")

DEFAULT_BASE_URL = "https://files.local"

# Policy schema: key -> validator
_POLICY_SCHEMA = {
    "expires_in": lambda v: isinstance(v, int) and v > 0,
    "methods": lambda v: isinstance(v, list) and v
        and all(m in {"GET", "PUT", "POST", "DELETE", "HEAD"} for m in v),
    "max_size": lambda v: isinstance(v, int) and v > 0,
    "content_types": lambda v: isinstance(v, list) and all(isinstance(c, str) for c in v),
    "ip": lambda v: isinstance(v, str) and v,
}


def _canonical(key: str, exp: int, policy_b64: Optional[str] = None) -> bytes:
    """THE single canonical signing payload used by every sign AND verify path."""
    base = f"{key}:{exp}"
    if policy_b64:
        base += f":{policy_b64}"
    return base.encode()


def _sig(secret: str, key: str, exp: int, policy_b64: Optional[str] = None) -> str:
    return hmac.new(secret.encode(), _canonical(key, exp, policy_b64), hashlib.sha256).hexdigest()


def sign(key: str, secret: str, expires_in: int = 3600, now: int | None = None) -> str:
    """Produce an expiring signed token for an object key: 'key?exp=..&sig=..'."""
    exp = (now or int(time.time())) + expires_in
    return f"{key}?exp={exp}&sig={_sig(secret, key, exp)}"


def verify(signed: str, secret: str, now: int | None = None) -> bool:
    try:
        key, qs = signed.split("?", 1)
        params = parse_qs(qs)
        exp = int(params.get("exp", [""])[0])
        if exp < (now or int(time.time())):
            return False
        return hmac.compare_digest(_sig(secret, key, exp), params.get("sig", [""])[0])
    except Exception:
        return False


def _key_from_url(url: str) -> Tuple[str, Dict[str, List[str]]]:
    parsed = urlparse(url)
    if not all([parsed.scheme, parsed.netloc, parsed.path]):
        raise ValueError("Invalid signed URL format")
    return parsed.path.lstrip("/"), parse_qs(parsed.query)


def generate_signed_url(key: str, secret: str, expires_in: int = 3600,
                        now: int | None = None, base_url: str = DEFAULT_BASE_URL) -> str:
    """Full signed URL. Signature covers the SAME canonical payload verify_signed_url checks."""
    key = key.lstrip("/")
    exp = (now or int(time.time())) + expires_in
    return f"{base_url.rstrip('/')}/{quote(key)}?exp={exp}&sig={_sig(secret, key, exp)}"


def verify_signed_url(url: str, secret: str,
                      now: int | None = None) -> Tuple[bool, Optional[str], Optional[int]]:
    """Returns (ok, key, exp). Uses the same canonical payload as generate_signed_url."""
    try:
        key, qs = _key_from_url(url)
        exp = int(qs.get("exp", [""])[0])
    except Exception:
        return False, None, None
    if exp < (now or int(time.time())):
        return False, None, None
    if not hmac.compare_digest(_sig(secret, key, exp), qs.get("sig", [""])[0]):
        return False, None, None
    return True, key, exp


def sign_with_policy(key: str, secret: str, policy: Dict[str, Any],
                     now: int | None = None, base_url: str = DEFAULT_BASE_URL) -> str:
    """Signed URL carrying a JSON policy; the policy is signed alongside key:exp."""
    if not validate_policy(policy):
        raise ValueError(f"invalid policy: {policy!r}")
    key = key.lstrip("/")
    expires_in = int(policy.get("expires_in", 3600))
    exp = (now or int(time.time())) + expires_in
    policy_b64 = base64.urlsafe_b64encode(
        json.dumps(policy, sort_keys=True).encode()).decode().rstrip("=")
    sig = _sig(secret, key, exp, policy_b64)
    return (f"{base_url.rstrip('/')}/{quote(key)}"
            f"?exp={exp}&policy={policy_b64}&sig={sig}")


def verify_with_policy(url: str, secret: str,
                       now: int | None = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Verify a policy-carrying URL; returns (ok, policy_dict)."""
    try:
        key, qs = _key_from_url(url)
        exp = int(qs.get("exp", [""])[0])
        policy_b64 = qs.get("policy", [""])[0]
        if not policy_b64:
            return False, None
    except Exception:
        return False, None
    if exp < (now or int(time.time())):
        return False, None
    if not hmac.compare_digest(_sig(secret, key, exp, policy_b64),
                               qs.get("sig", [""])[0]):
        return False, None
    try:
        padded = policy_b64 + "=" * (-len(policy_b64) % 4)
        policy = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return False, None
    if not validate_policy(policy):
        return False, None
    return True, policy


def generate_bulk_signed_urls(items: List[Dict[str, Any]], secret: str,
                              expires_in: int = 3600,
                              now: int | None = None) -> List[Dict[str, Any]]:
    signed_items = []
    for item in items:
        key = item.get("key")
        if not key:
            raise ValueError("Item must have a 'key' field")
        url = generate_signed_url(key, secret, expires_in, now)
        signed_items.append({**item, "url": url})
    return signed_items


def audit_signed_url(url: str, secret: str,
                     now: int | None = None) -> Optional[Dict[str, Any]]:
    """Verify a URL and emit + return a real audit record (never the secret)."""
    checked_at = now or int(time.time())
    ok, key, exp = verify_signed_url(url, secret, now)
    record = {
        "event": "signed_url_access",
        "url_path": urlparse(url).path,
        "key": key,
        "exp": exp,
        "verified": ok,
        "checked_at": checked_at,
    }
    log.info("signed_url audit key=%s verified=%s exp=%s", key, ok, exp)
    return record if ok else None


def configure_signature_policy(policy: Dict[str, Any],
                               default_policy: Dict[str, Any]) -> Dict[str, Any]:
    merged_policy = {**default_policy}
    for key, value in policy.items():
        if key in merged_policy:
            merged_policy[key] = value
    return merged_policy


def validate_policy(policy: Dict[str, Any]) -> bool:
    """Schema check: known keys only, each with the right type/shape."""
    if not isinstance(policy, dict) or not policy:
        return False
    for k, v in policy.items():
        check = _POLICY_SCHEMA.get(k)
        if check is None or not check(v):
            return False
    return True


def _selftest() -> bool:
    secret, now = "s3cret", 1_700_000_000

    # token sign/verify roundtrip
    tok = sign("a/b.txt", secret, 60, now)
    assert verify(tok, secret, now)
    assert not verify(tok, secret, now + 61)          # expired
    assert not verify(tok, "wrong", now)              # bad secret
    assert not verify(tok.replace("sig=", "sig=00"), secret, now)  # tampered

    # generate/verify URL: SAME canonical payload -> verifies
    url = generate_signed_url("docs/report.pdf", secret, 300, now)
    ok, key, exp = verify_signed_url(url, secret, now)
    assert ok and key == "docs/report.pdf" and exp == now + 300, (ok, key, exp)
    assert verify_signed_url(url, secret, now + 301)[0] is False
    assert verify_signed_url(url.replace("report", "other"), secret, now)[0] is False

    # policy flow
    pol = {"methods": ["GET"], "max_size": 1024, "expires_in": 120}
    purl = sign_with_policy("x/y.bin", secret, pol, now)
    ok, got = verify_with_policy(purl, secret, now)
    assert ok and got == pol, got
    assert verify_with_policy(purl, secret, now + 121) == (False, None)
    # tampering with the policy breaks the signature
    tampered = purl.replace("policy=", "policy=AA")
    assert verify_with_policy(tampered, secret, now)[0] is False

    # validate_policy schema
    assert validate_policy(pol)
    assert not validate_policy({})
    assert not validate_policy({"methods": ["TRACE"]})
    assert not validate_policy({"unknown_key": 1})
    assert not validate_policy({"max_size": -5})
    try:
        sign_with_policy("k", secret, {"bogus": 1}, now)
        raise AssertionError("invalid policy accepted")
    except ValueError:
        pass

    # audit record
    rec = audit_signed_url(url, secret, now)
    assert rec and rec["verified"] and rec["key"] == "docs/report.pdf"
    assert "secret" not in json.dumps(rec) and secret not in json.dumps(rec)
    assert audit_signed_url(url, secret, now + 999) is None

    # bulk
    bulk = generate_bulk_signed_urls([{"key": "a"}, {"key": "b"}], secret, 60, now)
    assert all(verify_signed_url(i["url"], secret, now)[0] for i in bulk)

    print("signed_urls selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
