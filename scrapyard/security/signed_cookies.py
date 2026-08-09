"""
signed_cookies — Tamper-evident signed cookies.

### PART-META-JSON
{
  "name": "signed_cookies",
  "layer": "security",
  "purpose": "Tamper-evident signed cookies.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "itsdangerous"
  ],
  "inputs": "Public API: sign(data, secret); unsign(token, secret); sign_with_policy(data, secret, policy); unsign_with_policy(token, secret, policy); generate_policy(expiration, max_size, allowed_keys); PolicyConfig(...); AuditInfo(...); UnsignError(...) (plus more).",
  "outputs": "Returns: sign -> str; unsign -> Optional[dict]; sign_with_policy -> str; unsign_with_policy -> Optional[dict]; generate_policy -> PolicyConfig.",
  "files_created": [],
  "security_notes": "Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `sign` from `scrapyard.security.signed_cookies` and call it as shown in `example`; run `py -m scrapyard.security.signed_cookies` to see its offline selftest.",
  "example": "from scrapyard.security.signed_cookies import sign",
  "import_path": "scrapyard.security.signed_cookies"
}
### END-PART-META
"""
from __future__ import annotations
import hmac
import hashlib
import base64
import json
from typing import *
from datetime import datetime, timedelta
from dataclasses import dataclass

STATUS = "core"

# Internal field carrying the issue time (epoch seconds) so unsign_with_policy
# can enforce PolicyConfig.expiration. Stripped from the returned payload.
_ISSUED_AT_KEY = "_sc_iat"

@dataclass(frozen=True)
class PolicyConfig:
    expiration: int = 3600
    max_size: int = 1024
    allowed_keys: Optional[Set[str]] = None

@dataclass(frozen=True)
class AuditInfo:
    user: str
    time: datetime
    ip: str

def sign(data: dict, secret: str) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    sig = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"

def unsign(token: str, secret: str) -> Optional[dict]:
    try:
        raw, sig = token.split(".", 1)
        expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        return json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
    except Exception as e:
        raise ValueError("Invalid token format") from e

def sign_with_policy(data: dict, secret: str, policy: PolicyConfig) -> str:
    data = serialize_data(data, policy)
    # Stamp the issue time so expiration can be enforced on unsign. Added AFTER
    # serialize_data so the policy's allowed_keys/max_size checks see only the
    # caller's own keys.
    payload = dict(data)
    payload[_ISSUED_AT_KEY] = int(datetime.now().timestamp())
    return sign(payload, secret)

def unsign_with_policy(token: str, secret: str, policy: PolicyConfig) -> Optional[dict]:
    raw_data = unsign(token, secret)
    if raw_data is None:
        return None
    return deserialize_data(raw_data, policy)

def generate_policy(expiration: int = 3600, max_size: int = 1024, allowed_keys: Optional[Set[str]] = None) -> PolicyConfig:
    return PolicyConfig(expiration=expiration, max_size=max_size, allowed_keys=allowed_keys)

def serialize_data(data: Any, policy: PolicyConfig) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Data must be a dictionary")
    if policy.allowed_keys is not None and not all(key in policy.allowed_keys for key in data.keys()):
        raise ValueError("Data contains disallowed keys")
    if len(json.dumps(data)) > policy.max_size:
        raise ValueError(f"Serialized data exceeds max size of {policy.max_size} bytes")
    return data

def deserialize_data(raw: Any, policy: PolicyConfig) -> Optional[dict]:
    # `raw` is the already-verified dict returned by unsign(); it is NOT a token,
    # so it must NOT be re-unsigned. Enforce expiration and allowed_keys here,
    # then strip the internal issue-time field before returning.
    if not isinstance(raw, dict):
        return None
    data = dict(raw)
    issued_at = data.pop(_ISSUED_AT_KEY, None)
    if policy.expiration is not None and issued_at is not None:
        try:
            age = datetime.now().timestamp() - float(issued_at)
        except (TypeError, ValueError):
            return None
        if age > policy.expiration:
            return None
    if policy.allowed_keys is not None and not all(key in policy.allowed_keys for key in data.keys()):
        return None
    return data

def audit_sign(data: dict, secret: str, audit_info: AuditInfo) -> str:
    data["audit"] = audit_info.__dict__
    return sign_with_policy(data, secret, PolicyConfig())

def audit_unsign(token: str, secret: str) -> Tuple[dict, Optional[AuditInfo]]:
    raw_data = unsign(token, secret)
    if raw_data is None:
        return {}, None
    data = raw_data.copy()
    data.pop(_ISSUED_AT_KEY, None)  # internal issue-time stamp, not caller data
    audit_info_dict = data.pop("audit", {})
    return data, AuditInfo(**audit_info_dict)

def sign_with_versioning(data: dict, secret: str, version: int) -> str:
    data["version"] = version
    return sign(data, secret)

def unsign_with_versioning(token: str, secret: str, version: int) -> Optional[dict]:
    raw_data = unsign(token, secret)
    if raw_data is None or "version" not in raw_data or raw_data["version"] != version:
        return None
    return raw_data

def bulk_sign(data_list: List[Dict], secret: str, policy: PolicyConfig, parallel: bool = False) -> List[str]:
    if parallel:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = []
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(sign_with_policy, data, secret, policy) for data in data_list]
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    raise ValueError("Error during signing") from e
        return results
    else:
        return [sign_with_policy(data, secret, policy) for data in data_list]

def bulk_unsign(tokens: List[str], secret: str, policy: PolicyConfig) -> List[Union[dict, UnsignError]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = []
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(unsign_with_policy, token, secret, policy) for token in tokens]
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is None:
                    results.append(UnsignError("Invalid token"))
                else:
                    results.append(result)
            except Exception as e:
                raise ValueError("Error during unsigning") from e
    return results

@dataclass(frozen=True)
class UnsignError(Exception):
    message: str = "Unknown error"


def _selftest() -> None:
    """Offline, falsifiable self-test of the HMAC sign/unsign cookie logic."""
    secret = "cookie-signing-secret"
    data = {"user_id": 7, "role": "admin"}

    # 1) roundtrip: unsign(sign(x)) == x
    tok = sign(data, secret)
    assert unsign(tok, secret) == data, "signed cookie must round-trip"

    # 2) NEGATIVE: a tampered SIGNATURE fails verification (returns None)
    raw, sig = tok.split(".", 1)
    tampered_sig = f"{raw}.{'f' * len(sig)}"
    assert unsign(tampered_sig, secret) is None, "tampered signature must not verify"

    # 3) NEGATIVE: a tampered PAYLOAD (privilege escalation attempt) fails —
    #    re-encode role=admin -> role=root without re-signing.
    forged_payload = base64.urlsafe_b64encode(
        json.dumps({"user_id": 7, "role": "root"}, separators=(",", ":")).encode()
    ).decode()
    forged = f"{forged_payload}.{sig}"
    assert unsign(forged, secret) is None, "payload tampering must invalidate the cookie"

    # 4) NEGATIVE: the WRONG secret cannot verify a valid token
    assert unsign(tok, "attacker-secret") is None, "wrong secret must not verify"

    # 5) versioning: correct version passes, wrong version rejected
    vtok = sign_with_versioning({"x": 1}, secret, version=3)
    assert unsign_with_versioning(vtok, secret, version=3) == {"x": 1, "version": 3}
    assert unsign_with_versioning(vtok, secret, version=2) is None, "version mismatch rejected"

    # 6) EXPLOIT REGRESSION: sign_with_policy -> unsign_with_policy round-trip.
    #    Previously deserialize_data re-unsigned an already-decoded dict and
    #    raised ValueError("Invalid token format").
    policy = generate_policy(expiration=3600, allowed_keys={"user_id", "role"})
    ptok = sign_with_policy(data, secret, policy)
    assert unsign_with_policy(ptok, secret, policy) == data, \
        "sign_with_policy/unsign_with_policy must round-trip"
    assert _ISSUED_AT_KEY not in unsign_with_policy(ptok, secret, policy), \
        "internal issue-time field must not leak into returned data"

    # 6a) a tampered policy cookie fails (returns None, does not verify)
    praw, psig = ptok.split(".", 1)
    tampered_policy = f"{praw}.{'f' * len(psig)}"
    assert unsign_with_policy(tampered_policy, secret, policy) is None, \
        "tampered policy cookie must fail verification"
    assert unsign_with_policy(ptok, "wrong-secret", policy) is None, \
        "wrong secret must fail policy verification"

    # 6b) EXPLOIT REGRESSION: an EXPIRED signed cookie must fail verification.
    #     Backdate the issue-time stamp past the policy expiration.
    short_policy = generate_policy(expiration=60, allowed_keys={"user_id", "role"})
    expired_payload = dict(data)
    expired_payload[_ISSUED_AT_KEY] = int(datetime.now().timestamp()) - 600  # 10 min old
    expired_tok = sign(expired_payload, secret)  # validly signed, but stale
    assert unsign(expired_tok, secret) is not None, "precondition: signature is valid"
    assert unsign_with_policy(expired_tok, secret, short_policy) is None, \
        "expired signed cookie must fail verification"
    # a fresh cookie under the same short policy still passes
    fresh_tok = sign_with_policy(data, secret, short_policy)
    assert unsign_with_policy(fresh_tok, secret, short_policy) == data, \
        "fresh cookie within expiration must verify"

    print("signed_cookies: OK (13 assertions incl. tamper + wrong-secret + "
          "version + policy-roundtrip + expiration negatives)")


if __name__ == "__main__":
    _selftest()
