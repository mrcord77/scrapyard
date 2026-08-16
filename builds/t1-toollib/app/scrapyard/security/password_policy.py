"""
password_policy — Enforce password strength + breach check.

### PART-META-JSON
{
  "name": "password_policy",
  "layer": "security",
  "purpose": "Enforce password strength + breach check.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure_policy(rules); check_breach(password, *, api_key, breach_db_url); enforce(password, *, min_len); score_strength(password); to_dict(password, *, include_breach); PolicyError(...); BreachCheckError(...); InvalidPolicyRuleError(...) (plus more).",
  "outputs": "Returns: configure_policy -> None; check_breach -> bool; enforce -> None; score_strength -> int; to_dict -> Dict[str, Union[str, bool]].",
  "files_created": [],
  "security_notes": "Makes outbound network calls; set timeouts, validate URLs/hosts, and never send secrets to untrusted endpoints.",
  "ai_usage": "Import `configure_policy` from `scrapyard.security.password_policy` and call it as shown in `example`; run `py -m scrapyard.security.password_policy` to see its offline selftest.",
  "example": "from scrapyard.security.password_policy import configure_policy",
  "import_path": "scrapyard.security.password_policy"
}
### END-PART-META
"""
from typing import Any, Callable, Dict, List, Optional, Union
import re
import httpx
from pydantic import BaseModel, ValidationError

STATUS = "core"
_AUDIT_HOOKS: List[Callable[[str, dict], None]] = []

class PolicyError(ValueError):
    pass

class BreachCheckError(Exception):
    pass

class InvalidPolicyRuleError(PolicyError):
    pass

class BulkEnforceError(Exception):
    pass

class ConfiguredPolicy(BaseModel):
    min_length: int
    required_characters: List[str] = [r"[A-Z]", r"[a-z]", r"\d"]
    custom_rules: Dict[str, Any]

def configure_policy(rules: Optional[Dict[str, Any]] = None) -> None:
    global CONFIGURED_POLICY
    if rules is not None:
        try:
            CONFIGURED_POLICY = ConfiguredPolicy(**rules)
        except ValidationError as e:
            raise InvalidPolicyRuleError("Invalid policy rule") from e

def check_breach(password: str, *, api_key: str, breach_db_url: str) -> bool:
    url = f"{breach_db_url}/check"
    headers = {"X-API-Key": api_key}
    data = {"password": password}
    try:
        response = httpx.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()["result"]
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        raise BreachCheckError("API unavailable") from e

def enforce(password: str, *, min_len: int = 10) -> None:
    issues = check(password, min_len=min_len)
    if issues:
        for hook in tuple(_AUDIT_HOOKS):
            hook("password_rejected", {"issues": list(issues), "length": len(password or "")})
        raise PolicyError("; ".join(issues))
    for hook in tuple(_AUDIT_HOOKS):
        hook("password_accepted", {"length": len(password)})

def score_strength(password: str) -> int:
    length_score = max(len(password) - 8, 0)
    complexity_score = sum([password.count(c) for c in "!@#$%^&*()_+-=[]{}|;:,.<>?"])
    return (length_score + complexity_score) // 2

def to_dict(password: str, *, include_breach: bool = False) -> Dict[str, Union[str, bool]]:
    breach_info = check_breach(password, api_key="YOUR_API_KEY", breach_db_url="https://api.pwnedpasswords.com") if include_breach else None
    return {
        "strength_score": score_strength(password),
        "is_breached": breach_info,
    }

def get_current_policy() -> Dict[str, Any]:
    return CONFIGURED_POLICY.dict()

def check_with_mfa(password: str, mfa_required: bool = False) -> List[str]:
    issues = check(password)
    if mfa_required and not any(re.search(pattern, password) for pattern in CONFIGURED_POLICY.required_characters):
        issues.append("must contain a special character")
    return issues

class PolicyErrorMessages(BaseModel):
    min_length: str
    required_characters: Dict[str, str]

def set_error_messages(messages: Dict[str, Any]) -> None:
    global ERROR_MESSAGES
    try:
        ERROR_MESSAGES = PolicyErrorMessages(**messages).dict()
    except ValidationError as e:
        raise InvalidPolicyRuleError("Invalid error messages") from e

def register_audit_hook(hook: Callable[[str, dict], None]) -> None:
    if not callable(hook):
        raise TypeError("audit hook must be callable")
    if hook not in _AUDIT_HOOKS:
        _AUDIT_HOOKS.append(hook)

def validate_custom_rule(rule: Dict[str, Any]) -> bool:
    try:
        ConfiguredPolicy(**rule)
        return True
    except ValidationError:
        return False

def enforce_bulk(passwords: List[str], *, min_len: int = 10) -> List[PolicyError]:
    errors = []
    for idx, password in enumerate(passwords):
        issues = check(password, min_len=min_len)
        if issues:
            errors.append(PolicyError(f"Invalid password at index {idx}: {'; '.join(issues)}"))
    return errors

CONFIGURED_POLICY: Optional[ConfiguredPolicy] = None
ERROR_MESSAGES: Optional[PolicyErrorMessages] = None

# original semantics: a letter and a digit (NOT case classes) unless configured
_DEFAULT_REQUIRED = [(r"[A-Za-z]", "must contain a letter"),
                     (r"\d", "must contain a digit")]

def check(password: str, *, min_len: int = 10) -> List[str]:
    """Return a list of policy violations (empty = ok)."""
    issues = []
    if len(password or "") < min_len:
        issues.append(f"must be at least {min_len} characters")
    if CONFIGURED_POLICY is not None:
        for pattern in CONFIGURED_POLICY.required_characters:
            if not re.search(pattern, password or ""):
                issues.append(f"must contain a {pattern}")
    else:
        for pattern, msg in _DEFAULT_REQUIRED:
            if not re.search(pattern, password or ""):
                issues.append(msg)
    return issues


def _selftest() -> None:
    """Offline, falsifiable self-test of the strength policy (no network/breach call)."""
    # 1) NEGATIVE: a too-short password is rejected with a length issue
    short = check("Ab1", min_len=10)
    assert any("at least 10" in i for i in short), "short password must be flagged"

    # 2) NEGATIVE: a long-but-all-letters password lacks a digit
    no_digit = check("abcdefghijkl", min_len=10)
    assert any("digit" in i for i in no_digit), "missing digit must be flagged"

    # 3) a compliant password passes cleanly (empty issue list)
    assert check("Str0ngPassphrase!", min_len=10) == [], "strong password must pass"

    # 4) NEGATIVE: enforce() raises PolicyError on a weak password
    raised = False
    events = []
    register_audit_hook(lambda event, data: events.append((event, data)))
    try:
        enforce("weak", min_len=10)
    except PolicyError:
        raised = True
    assert raised, "enforce() must raise on a weak password"
    # ...and does NOT raise on a strong one
    enforce("Str0ngPassphrase!", min_len=10)
    assert [event for event, _ in events] == ["password_rejected", "password_accepted"]
    assert all("password" not in data for _, data in events)

    # 5) score_strength ranks a stronger password above a weaker one
    assert score_strength("Str0ng!Pass#word$") > score_strength("aaaaaaaa"), \
        "stronger password must score higher"

    # 6) enforce_bulk reports one error per bad entry, none for good ones
    errs = enforce_bulk(["weak", "Str0ngPassphrase!"], min_len=10)
    assert len(errs) == 1, "exactly the weak password should error in bulk"

    print("password_policy: OK (6 assertions incl. weak-password rejection negatives)")


if __name__ == "__main__":
    _selftest()
