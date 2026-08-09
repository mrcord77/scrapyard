"""
retention_policy_editor — Create and update data-retention policies (validated, in-memory registry).

### PART-META-JSON
{
  "name": "retention_policy_editor",
  "layer": "audit_governance",
  "purpose": "Editor for data-retention policies: create_retention_policy() validates rule dicts (each needs 'condition' and 'action'), assigns rule/policy ids, and stores the policy in a module-level in-memory registry; update_retention_policy() replaces a policy's rules; get_retention_policy() reads one back. HONEST LIMIT: storage is process-local memory only - there is no database persistence, and policies are NOT enforced against any data store by this part; enforcement and durable storage belong to the composing app.",
  "status": "core",
  "dependencies": [],
  "inputs": "create_retention_policy(name, [{'condition': 'age > 30', 'action': 'delete'}, ...]); update_retention_policy(policy_id, new_rules); get_retention_policy(policy_id).",
  "outputs": "Integer policy ids; RetentionPolicy dataclasses (frozen RetentionPolicyRule entries). Malformed rules raise ValueError; unknown policy ids raise KeyError.",
  "files_created": [],
  "security_notes": "Retention rules decide what data gets deleted or archived downstream - treat write access to this editor as privileged and gate it behind admin authorization in the composing app. Conditions are stored as opaque strings and are NOT parsed or executed here (no eval), but whatever engine later interprets them must treat them as untrusted input. In-memory registry means policies vanish on restart and are not shared across processes - do not rely on this part alone for compliance-mandated retention records.",
  "ai_usage": "pid = create_retention_policy('logs-90d', [{'condition': 'age_days > 90', 'action': 'delete'}]); update_retention_policy(pid, new_rules).",
  "example": "from scrapyard.audit_governance.retention_policy_editor import create_retention_policy",
  "import_path": "scrapyard.audit_governance.retention_policy_editor"
}
### END-PART-META
"""
from dataclasses import dataclass
from itertools import count
from typing import List, Dict, Any
import logging
import threading

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionPolicyRule:
    rule_id: int
    condition: str
    action: str


@dataclass
class RetentionPolicy:
    policy_id: int
    name: str
    rules: List[RetentionPolicyRule]


_policies: Dict[int, RetentionPolicy] = {}
_policy_ids = count(1)
_lock = threading.Lock()


def _validate_rules(rules: List[Dict[str, Any]]) -> None:
    if not all(isinstance(rule, dict) and 'condition' in rule and 'action' in rule
               for rule in rules):
        raise ValueError("Invalid rule format: each rule needs 'condition' and 'action'")


def _build_rules(rules: List[Dict[str, Any]]) -> List[RetentionPolicyRule]:
    return [
        RetentionPolicyRule(rule_id=i, condition=str(rule['condition']),
                            action=str(rule['action']))
        for i, rule in enumerate(rules, start=1)
    ]


def create_retention_policy(name: str, rules: List[Dict[str, Any]]) -> int:
    """
    Create a new retention policy with the given name and rules.

    :param name: Name of the policy
    :param rules: List of dicts, each with 'condition' and 'action' keys
    :return: The ID of the created policy
    :raises ValueError: If any rule is malformed
    """
    _validate_rules(rules)
    with _lock:
        policy_id = next(_policy_ids)
        _policies[policy_id] = RetentionPolicy(
            policy_id=policy_id, name=name, rules=_build_rules(rules))
    logger.info("Created retention policy %s (id=%s)", name, policy_id)
    return policy_id


def update_retention_policy(policy_id: int, new_rules: List[Dict[str, Any]]) -> None:
    """
    Replace the rules of an existing retention policy.

    :param policy_id: ID of the policy to be updated
    :param new_rules: List of dicts, each with 'condition' and 'action' keys
    :raises ValueError: If any rule is malformed
    :raises KeyError: If the policy does not exist
    """
    _validate_rules(new_rules)
    with _lock:
        if policy_id not in _policies:
            raise KeyError(f"No retention policy with id {policy_id}")
        _policies[policy_id].rules = _build_rules(new_rules)
    logger.info("Updated retention policy id=%s", policy_id)


def get_retention_policy(policy_id: int) -> RetentionPolicy:
    """Return the stored policy; raises KeyError if absent."""
    with _lock:
        return _policies[policy_id]


def _selftest() -> None:
    """Self-test validating create/update/read and error paths. Raises on failure."""
    policy_id = create_retention_policy(
        "TestPolicy", [{"condition": "age > 30", "action": "delete"}])
    policy = get_retention_policy(policy_id)
    assert policy.name == "TestPolicy"
    assert len(policy.rules) == 1
    assert policy.rules[0].condition == "age > 30"
    assert policy.rules[0].action == "delete"

    update_retention_policy(policy_id, [{"condition": "age < 40", "action": "archive"}])
    policy = get_retention_policy(policy_id)
    assert len(policy.rules) == 1
    assert policy.rules[0].action == "archive"

    # Second policy gets a distinct id.
    other_id = create_retention_policy(
        "Other", [{"condition": "size > 1", "action": "archive"}])
    assert other_id != policy_id

    # Malformed rules rejected.
    try:
        create_retention_policy("Bad", [{"condition": "x"}])
        raise AssertionError("expected ValueError for malformed rule")
    except ValueError:
        pass

    # Unknown policy id rejected.
    try:
        update_retention_policy(999999, [{"condition": "c", "action": "a"}])
        raise AssertionError("expected KeyError for unknown policy id")
    except KeyError:
        pass

    logger.info("Self-test passed")


if __name__ == "__main__":
    _selftest()
