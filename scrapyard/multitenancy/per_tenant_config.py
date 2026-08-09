"""
per_tenant_config — Per-tenant settings/overrides.

### PART-META-JSON
{
  "name": "per_tenant_config",
  "layer": "multitenancy",
  "purpose": "Per-tenant settings/overrides.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: TenantConfig(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import `TenantConfig` from `scrapyard.multitenancy.per_tenant_config` and call it as shown in `example`; run `py -m scrapyard.multitenancy.per_tenant_config` to see its offline selftest.",
  "example": "from scrapyard.multitenancy.per_tenant_config import TenantConfig",
  "import_path": "scrapyard.multitenancy.per_tenant_config"
}
### END-PART-META
"""
from typing import Any, Callable, Dict
import os
import yaml
import json

class TenantConfig:
    """Per-tenant settings with a global default fallback."""
    def __init__(self, defaults: dict | None = None):
        self.defaults = defaults or {}
        self._by_tenant = {}

    def set(self, tenant_id: str, key: str, value: Any, policy: Callable[[str, str, Any], bool] = None) -> None:
        if policy and not policy(tenant_id, key, value):
            raise ValueError(f"Policy check failed for {tenant_id} - {key}")
        self._by_tenant.setdefault(tenant_id, {})[key] = value

    def get(self, tenant_id: str, key: str, default: Any = None) -> Any:
        return self._by_tenant.get(tenant_id, {}).get(key, self.defaults.get(key, default))

    def set_defaults(self, defaults: dict) -> None:
        self.defaults.update(defaults)

    def get_all(self, tenant_id: str) -> Dict[str, Any]:
        return {**self.defaults, **self._by_tenant.get(tenant_id, {})}

    def delete(self, tenant_id: str, key: str) -> None:
        if tenant_id in self._by_tenant and key in self._by_tenant[tenant_id]:
            del self._by_tenant[tenant_id][key]

    def clear(self, tenant_id: str) -> None:
        if tenant_id in self._by_tenant:
            self._by_tenant.pop(tenant_id)

    def configure_from_env(self, prefix: str = "TENANT_") -> None:
        for key, value in os.environ.items():
            if key.startswith(prefix):
                tenant_id = key[len(prefix):]
                self.set(tenant_id, key[len(prefix):], value)

    def load_from_file(self, path: str, format: str = "yaml") -> None:
        with open(path, 'r') as file:
            data = yaml.safe_load(file) if format == "yaml" else json.load(file)
            self.set_defaults(data)

    def get_with_fallback(self, tenant_id: str, key: str, fallback_key: str, default: Any = None) -> Any:
        value = self.get(tenant_id, key, None)
        return value or self.get(tenant_id, fallback_key, default)

    def set_if_not_exists(self, tenant_id: str, key: str, value: Any) -> None:
        if key not in self._by_tenant.get(tenant_id, {}):
            self.set(tenant_id, key, value)

    def get_all_tenants(self) -> Dict[str, Dict[str, Any]]:
        return {tenant_id: self.get_all(tenant_id) for tenant_id in self._by_tenant}

    def apply_policy(self, policy: Callable[[str, str, Any], bool]) -> None:
        self.policy = policy

    def serialize(self, tenant_id: str, format: str = "json") -> str:
        config = self.get_all(tenant_id)
        if format == "yaml":
            return yaml.dump(config)
        elif format == "json":
            return json.dumps(config, indent=2)

    def bulk_set(self, tenant_id: str, overrides: Dict[str, Any]) -> None:
        for key, value in overrides.items():
            self.set(tenant_id, key, value)

    def audit_log(self, tenant_id: str, action: str, details: Dict[str, Any]) -> None:
        # Placeholder for actual logging implementation
        print(f"Audit Log: {tenant_id} - {action}: {details}")

    def set_global_policy(self, policy: Callable[[str, str, Any], bool]) -> None:
        self.global_policy = policy

    def set_serializer(self, serializer: Callable[[Any], str]) -> None:
        self.serializer = serializer

    def set_deserializer(self, deserializer: Callable[[str], Any]) -> None:
        self.deserializer = deserializer


def _selftest() -> None:
    cfg = TenantConfig(defaults={"theme": "light", "limit": 10})
    cfg.set("t1", "theme", "dark")
    assert cfg.get("t1", "theme") == "dark"               # per-tenant override wins
    assert cfg.get("t1", "limit") == 10                   # falls back to default
    assert cfg.get("t2", "theme") == "light"              # other tenant does NOT see t1's value (isolation)
    assert cfg.get("t1", "missing_key", "dflt") == "dflt" # missing key -> provided default
    assert cfg.get("unknown_tenant", "unknown_key") is None   # missing tenant+key -> None (fail closed)

    cfg.set_if_not_exists("t1", "theme", "green")
    assert cfg.get("t1", "theme") == "dark"               # negative: existing value not clobbered
    cfg.set_if_not_exists("t1", "brand", "acme")
    assert cfg.get("t1", "brand") == "acme"

    deny = lambda tid, k, v: False
    try:                                                  # negative: rejecting policy blocks the write
        cfg.set("t1", "blocked", 1, policy=deny)
        raise AssertionError("policy rejection was not enforced")
    except ValueError:
        pass
    assert cfg.get("t1", "blocked") is None
    print("per_tenant_config selftest: PASS")


if __name__ == "__main__":
    _selftest()
