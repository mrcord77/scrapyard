"""
entitlement_gate — Gate features by billing plan/entitlement.

### PART-META-JSON
{
  "name": "entitlement_gate",
  "layer": "authorization",
  "purpose": "Plan-based entitlement gating: feature allow-lists with '*' plans, numeric usage limits (-1 = unlimited), named policy storage and enforcement (require/deny features + limit checks), env-driven plan configuration, and a structured audit hook.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Plan definitions (features set + limits dict); plan name, feature names, and current usage counts at check time.",
  "outputs": "Booleans, per-feature result dicts, EntitlementSummary, and policy-enforcement verdict dicts.",
  "files_created": [],
  "security_notes": "Fail-closed on unknown plans (PlanNotFoundError) rather than defaulting to allowed. Limits treat negative caps as unlimited; callers must pass true current usage or limits are meaningless. The optional injected store is only consulted through its get/set interface, so a misconfigured backend degrades to in-process plans instead of granting access. Env-config values are parsed strictly and reject malformed limit specs.",
  "ai_usage": "Build a Dict[str, Plan], construct Entitlements(plans), then call allows()/within_limit()/apply_entitlement_policy() at request time.",
  "example": "ents = Entitlements({'pro': Plan('pro', {'export'}, {'seats': 10})}); ents.allows('pro', 'export')",
  "import_path": "scrapyard.authorization.entitlement_gate"
}
### END-PART-META
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

STATUS = "core"

logger = logging.getLogger("scrapyard.authorization.entitlement_gate")


class PlanNotFoundError(Exception):
    pass

class InvalidFeatureError(Exception):
    pass

class InvalidLimitKeyError(Exception):
    pass

class PolicyNotFoundError(Exception):
    pass

class EntitlementPolicyError(Exception):
    pass


class EntitlementStore(Protocol):
    """Optional external backing store (e.g. a Redis client or any get/set object)."""
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: Any) -> Any: ...


@dataclass
class Plan:
    name: str
    features: set[str] = field(default_factory=set)
    limits: dict[str, int] = field(default_factory=dict)

@dataclass
class FeatureCheckResult:
    feature: str
    allowed: bool

@dataclass
class EntitlementSummary:
    plan_name: str
    features: Dict[str, bool]
    limits: Dict[str, int]


def serialize_entitlements(plans: Dict[str, Plan]) -> Dict[str, Dict[str, Any]]:
    serialized = {}
    for plan_name, plan in plans.items():
        serialized[plan_name] = {
            "features": {f: "*" in plan.features or f in plan.features for f in plan.features},
            "limits": {k: v for k, v in plan.limits.items()},
        }
    return serialized


class Entitlements:
    def __init__(self, plans: Dict[str, Plan], store: Optional[EntitlementStore] = None) -> None:
        """`store` is an OPTIONAL injected get/set backend (e.g. a Redis client).

        No client is constructed here; when store is None everything is in-process.
        """
        self._plans = plans
        self._store = store
        self._policies: Dict[str, Dict[str, Any]] = {}

    def allows(self, plan_name: str, feature: str) -> bool:
        if not (plan := self._plans.get(plan_name)):
            raise PlanNotFoundError(f"Plan '{plan_name}' not found.")
        return feature in plan.features or "*" in plan.features

    def limit(self, plan_name: str, key: str, default: int = 0) -> int:
        if not (plan := self._plans.get(plan_name)):
            raise PlanNotFoundError(f"Plan '{plan_name}' not found.")
        return plan.limits.get(key, default)

    def within_limit(self, plan_name: str, key: str, current: int) -> bool:
        cap = self.limit(plan_name, key)
        return cap < 0 or current < cap

    def check_entitlements(
        self,
        plan_name: str,
        features: List[str],
        limits: Dict[str, int],
    ) -> Dict[str, bool]:
        """Check features against the plan's feature set and each limits entry
        (key -> current usage) against the plan's limit caps.

        Returns one merged dict of name -> allowed. Feature names are checked as
        features; limit keys are checked as limits — never cross-used.
        """
        results: Dict[str, bool] = {feature: self.allows(plan_name, feature) for feature in features}
        for key, current in limits.items():
            results[key] = self.within_limit(plan_name, key, current)
        return results

    def apply_entitlement_policy(self, plan_name: str, policy: Dict[str, Any]) -> Dict[str, Any]:
        """Enforce a policy dict against a plan. Policy keys (all optional):

        - "require_features": list[str] — every feature must be allowed by the plan.
        - "deny_features": list[str] — none of these may be present on the plan.
        - "limits": dict[key, current_usage] — each must be within the plan cap.

        Returns {"allowed": bool, "violations": [...], "feature_results": {...},
        "limit_results": {...}}. Raises PlanNotFoundError for unknown plans and
        EntitlementPolicyError for a malformed policy.
        """
        if not isinstance(policy, dict):
            raise EntitlementPolicyError("policy must be a dict")
        if plan_name not in self._plans:
            raise PlanNotFoundError(f"Plan '{plan_name}' not found.")

        violations: List[str] = []
        feature_results: Dict[str, bool] = {}
        limit_results: Dict[str, bool] = {}

        for feature in policy.get("require_features", []) or []:
            ok = self.allows(plan_name, feature)
            feature_results[feature] = ok
            if not ok:
                violations.append(f"missing feature: {feature}")

        for feature in policy.get("deny_features", []) or []:
            present = self.allows(plan_name, feature)
            feature_results[feature] = not present
            if present:
                violations.append(f"denied feature present: {feature}")

        limits = policy.get("limits", {}) or {}
        if not isinstance(limits, dict):
            raise EntitlementPolicyError("policy['limits'] must be a dict of key -> current usage")
        for key, current in limits.items():
            ok = self.within_limit(plan_name, key, int(current))
            limit_results[key] = ok
            if not ok:
                violations.append(f"limit exceeded: {key} (current={current}, cap={self.limit(plan_name, key)})")

        return {
            "allowed": not violations,
            "violations": violations,
            "feature_results": feature_results,
            "limit_results": limit_results,
        }

    def get_entitlement_summary(self, plan_name: str) -> EntitlementSummary:
        if plan_name not in self._plans:
            raise PlanNotFoundError(f"Plan '{plan_name}' not found.")
        plan = self._plans[plan_name]
        features = {feature: self.allows(plan_name, feature) for feature in plan.features}
        limits = {key: self.limit(plan_name, key) for key in plan.limits.keys()}
        return EntitlementSummary(plan_name=plan_name, features=features, limits=limits)

    def bulk_check_entitlements(self, plan_names: List[str], features: List[str]) -> Dict[str, Dict[str, bool]]:
        results: Dict[str, Dict[str, bool]] = {}
        for plan_name in plan_names:
            try:
                results[plan_name] = self.check_entitlements(plan_name, features, {})
            except PlanNotFoundError:
                results[plan_name] = {feature: False for feature in features}
                logger.warning("bulk_check_entitlements: unknown plan %r treated as all-denied", plan_name)
        return results

    def audit_entitlement_check(self, plan_name: str, feature: str, result: bool, user_id: str) -> None:
        """Structured audit log for an entitlement decision."""
        logger.log(
            logging.INFO if result else logging.WARNING,
            "entitlement_check plan=%s feature=%s allowed=%s user=%s",
            plan_name, feature, result, user_id,
            extra={"audit": {
                "event": "entitlement_check",
                "plan": plan_name,
                "feature": feature,
                "allowed": result,
                "user_id": user_id,
            }},
        )

    def configure_entitlements_from_env(self, env_prefix: str = "ENTITLEMENT_") -> None:
        """Load plans from environment variables.

        - ENTITLEMENT_<PLAN>_FEATURE = "feat1,feat2"  (comma-separated feature names)
        - ENTITLEMENT_<PLAN>_LIMIT   = "seats=5,projects=10"  (key=int pairs)

        Order-independent: a LIMIT var may precede its FEATURE var. Loaded plans
        are merged over any existing plans of the same name.
        """
        from os import environ

        plans_dict: Dict[str, Plan] = {}
        for key in sorted(environ.keys()):
            if not key.startswith(env_prefix):
                continue
            remainder = key[len(env_prefix):]
            if "_" not in remainder:
                continue
            plan_name, kind = remainder.split("_", 1)
            value = environ[key]
            plan = plans_dict.setdefault(plan_name, Plan(name=plan_name))
            if kind == "FEATURE":
                for feat in (v.strip() for v in value.split(",")):
                    if feat:
                        plan.features.add(feat)
            elif kind == "LIMIT":
                for pair in (v.strip() for v in value.split(",")):
                    if not pair:
                        continue
                    if "=" not in pair:
                        raise InvalidLimitKeyError(
                            f"Invalid limit spec {pair!r} in {key}: expected 'name=int'")
                    limit_key, _, limit_val = pair.partition("=")
                    try:
                        plan.limits[limit_key.strip()] = int(limit_val.strip())
                    except ValueError as e:
                        raise InvalidLimitKeyError(f"Invalid limit value in {key}: {e}") from e
            # unknown kinds are ignored (forward compatibility)
        self._plans.update(plans_dict)

    def set_entitlement_policy(self, policy_name: str, policy: Dict[str, Any]) -> None:
        """Store a named policy for later enforcement via apply_named_policy/get_entitlement_policy."""
        if not isinstance(policy, dict):
            raise EntitlementPolicyError("policy must be a dict")
        self._policies[policy_name] = dict(policy)
        if self._store is not None:
            try:
                self._store.set(f"entitlement_policy:{policy_name}", repr(policy))
            except Exception:
                logger.exception("entitlement store write failed for policy %r", policy_name)

    def get_entitlement_policy(self, policy_name: str) -> Optional[Dict[str, Any]]:
        """Return a stored policy dict, or None if not set."""
        return self._policies.get(policy_name)

    def apply_named_policy(self, plan_name: str, policy_name: str) -> Dict[str, Any]:
        """Enforce a previously stored named policy against a plan."""
        policy = self._policies.get(policy_name)
        if policy is None:
            raise PolicyNotFoundError(f"Policy '{policy_name}' not found.")
        return self.apply_entitlement_policy(plan_name, policy)

    def reset_entitlements(self) -> None:
        self._plans = {}
        self._policies = {}


def _selftest() -> None:
    import os

    plans = {
        "basic": Plan(name="basic", features={"feature1", "feature2"}, limits={"limit1": 5}),
        "premium": Plan(name="premium", features={"feature1", "feature2", "feature3"},
                        limits={"limit1": 10, "limit2": -1}),
    }
    ents = Entitlements(plans)  # no store injected: fully in-process

    # feature gating
    assert ents.allows("basic", "feature1")
    assert not ents.allows("basic", "feature3")
    assert ents.allows("premium", "feature3")
    try:
        ents.allows("ghost", "feature1")
        raise AssertionError("unknown plan did not raise")
    except PlanNotFoundError:
        pass

    # limits: -1 means unlimited, missing key defaults to 0 cap (fail closed)
    assert ents.within_limit("basic", "limit1", 4)
    assert not ents.within_limit("basic", "limit1", 5)
    assert ents.within_limit("premium", "limit2", 10_000_000)
    assert not ents.within_limit("basic", "unknown_limit", 0)

    # check_entitlements: features checked as features, limit keys as limits
    res = ents.check_entitlements("basic", ["feature1", "feature3"], {"limit1": 2})
    assert res == {"feature1": True, "feature3": False, "limit1": True}

    # policy enforcement (implemented, no longer NotImplementedError)
    verdict = ents.apply_entitlement_policy("premium", {
        "require_features": ["feature1", "feature3"],
        "deny_features": ["beta_only"],
        "limits": {"limit1": 3},
    })
    assert verdict["allowed"] is True and verdict["violations"] == []
    verdict = ents.apply_entitlement_policy("basic", {
        "require_features": ["feature3"],
        "limits": {"limit1": 99},
    })
    assert verdict["allowed"] is False
    assert any("missing feature: feature3" in v for v in verdict["violations"])
    assert any("limit exceeded: limit1" in v for v in verdict["violations"])
    try:
        ents.apply_entitlement_policy("basic", "not-a-dict")  # type: ignore[arg-type]
        raise AssertionError("malformed policy accepted")
    except EntitlementPolicyError:
        pass

    # named policies round-trip
    ents.set_entitlement_policy("needs_f1", {"require_features": ["feature1"]})
    assert ents.get_entitlement_policy("needs_f1") == {"require_features": ["feature1"]}
    assert ents.apply_named_policy("basic", "needs_f1")["allowed"] is True
    try:
        ents.apply_named_policy("basic", "missing_policy")
        raise AssertionError("unknown policy did not raise")
    except PolicyNotFoundError:
        pass

    # bulk check treats unknown plans as all-denied
    bulk = ents.bulk_check_entitlements(["basic", "ghost"], ["feature1"])
    assert bulk["basic"]["feature1"] is True and bulk["ghost"]["feature1"] is False

    # env configuration: LIMIT before FEATURE must not KeyError; values parsed properly
    env_keys = {
        "ENTITLEMENT_TRIAL_LIMIT": "seats=3,projects=1",
        "ENTITLEMENT_TRIAL_FEATURE": "export,api_access",
    }
    old = {k: os.environ.get(k) for k in env_keys}
    os.environ.update(env_keys)
    try:
        ents.configure_entitlements_from_env()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert ents.allows("TRIAL", "export")
    assert ents.limit("TRIAL", "seats") == 3
    assert ents.limit("TRIAL", "projects") == 1
    assert not ents.within_limit("TRIAL", "seats", 3)

    # optional injected store is used through get/set only
    class DictStore:
        def __init__(self):
            self.data = {}
        def get(self, k):
            return self.data.get(k)
        def set(self, k, v):
            self.data[k] = v
    store = DictStore()
    ents2 = Entitlements({"p": Plan(name="p")}, store=store)
    ents2.set_entitlement_policy("pol", {"require_features": []})
    assert "entitlement_policy:pol" in store.data

    # summary + serialization + audit hook (no exception)
    summary = ents.get_entitlement_summary("basic")
    assert summary.plan_name == "basic" and summary.features["feature1"] is True
    ser = serialize_entitlements(plans)
    assert ser["premium"]["limits"]["limit2"] == -1
    ents.audit_entitlement_check("basic", "feature1", True, "user-1")

    ents2.reset_entitlements()
    assert ents2.get_entitlement_policy("pol") is None

    print("entitlement_gate selftest: PASS")


if __name__ == "__main__":
    _selftest()
