"""
feature_gates — Boolean/percentage feature flags per user/tenant.

### PART-META-JSON
{
  "name": "feature_gates",
  "layer": "authorization",
  "purpose": "Boolean/percentage feature flags per user/tenant.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: FeatureFlags(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import `FeatureFlags` from `scrapyard.authorization.feature_gates` and call it as shown in `example`; run `py -m scrapyard.authorization.feature_gates` to see its offline selftest.",
  "example": "from scrapyard.authorization.feature_gates import FeatureFlags",
  "import_path": "scrapyard.authorization.feature_gates"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
class FeatureFlags:
    """Static + per-user feature flags. percentage() does sticky % rollouts."""
    def __init__(self, flags: dict | None=None): self.flags=flags or {}
    def enabled(self, name: str, user_id=None) -> bool:
        v=self.flags.get(name, False)
        if isinstance(v, bool): return v
        if isinstance(v, dict) and "percent" in v and user_id is not None:
            import hashlib
            h=int(hashlib.sha256(f"{name}:{user_id}".encode()).hexdigest(),16)%100
            return h < v["percent"]
        return bool(v)


def _selftest() -> None:
    ff = FeatureFlags({"new_ui": True, "beta": False, "rollout": {"percent": 50}})
    assert ff.enabled("new_ui") is True
    assert ff.enabled("beta") is False
    assert ff.enabled("missing") is False                 # negative: unknown flag fails closed

    v1 = ff.enabled("rollout", user_id=12345)
    v2 = ff.enabled("rollout", user_id=12345)
    assert v1 == v2 and isinstance(v1, bool)              # sticky per (flag, user)

    edge = FeatureFlags({"none": {"percent": 0}, "all": {"percent": 100}})
    assert edge.enabled("none", user_id=999) is False     # 0% never enables
    assert edge.enabled("all", user_id=999) is True       # 100% always enables
    print("feature_gates selftest: PASS")


if __name__ == "__main__":
    _selftest()
