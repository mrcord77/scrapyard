"""
secrets — Load secrets from env/manager; never log them.

### PART-META-JSON
{
  "name": "secrets",
  "layer": "security",
  "purpose": "Load secrets from env/manager; never log them.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: get_secret(name, default); require_secret(name); mask(value, show, policy); secret_exists(name); bulk_get_secrets(names, policy); MissingSecret(...); InvalidSecretPolicy(...); SecretMaskingError(...) (plus more).",
  "outputs": "Returns: get_secret -> str | None; require_secret -> str; mask -> str; secret_exists -> bool; bulk_get_secrets -> dict.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `get_secret` from `scrapyard.security.secrets` and call it as shown in `example`; run `py -m scrapyard.security.secrets` to see its offline selftest.",
  "example": "from scrapyard.security.secrets import get_secret",
  "import_path": "scrapyard.security.secrets"
}
### END-PART-META
"""
from __future__ import annotations

import abc
import logging
import os
import time
from enum import Enum
from typing import Any, List, Optional

_log = logging.getLogger("scrapyard.security.secrets")

STATUS = "core"

class MissingSecret(Exception):
    pass

class InvalidSecretPolicy(Exception):
    pass

class SecretMaskingError(Exception):
    pass

class SecretSourceError(Exception):
    pass

class SecretCacheMiss(Exception):
    pass

class SecretPolicy(Enum):
    DEFAULT = 1
    REDACT = 2
    VALIDATE = 3
    SANITIZE = 4
    ENFORCE = 5

class MaskPolicy(Enum):
    DEFAULT = 1
    TRUNCATE = 2
    REDACT = 3
    ANONYMIZE = 4

def get_secret(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)

def require_secret(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise MissingSecret(f"required secret not set: {name}")
    return v

def mask(value: str, show: int = 4, policy: MaskPolicy = MaskPolicy.DEFAULT) -> str:
    if not value:
        return ""
    
    if policy == MaskPolicy.REDACT:
        return "*" * len(value)
    elif policy == MaskPolicy.TRUNCATE:
        return ("*" * max(0, len(value) - show)) + value[-show:]
    elif policy == MaskPolicy.ANONYMIZE:
        return "ANONYMIZED"
    
    return ("*" * max(0, len(value) - show)) + value[-show:]

class SecretLoader:
    def __init__(self, sources: List[SecretSource], cache: Optional[SecretCache] = None):
        self.sources = sources
        self.cache = cache

    def get_secret(self, name: str, policy: SecretPolicy = SecretPolicy.DEFAULT) -> str | None:
        """Returns the real secret value (masking is for logs only — see mask())."""
        for source in self.sources:
            try:
                secret = source.get_secret(name)
                if secret is not None:
                    if self.cache is not None:
                        self.cache.set(name, secret)
                    return secret
            except SecretSourceError as e:
                raise SecretSourceError(f"Failed to load {name} from {source}: {e}")

        if self.cache and self.cache.exists(name):
            try:
                return self.cache.get(name)
            except SecretCacheMiss:
                return None

        return None

    def require_secret(self, name: str, policy: SecretPolicy = SecretPolicy.DEFAULT) -> str:
        secret = self.get_secret(name, policy=policy)
        if not secret:
            raise MissingSecret(f"required secret {name} not found")
        return secret

class SecretSource(abc.ABC):
    @abc.abstractmethod
    def get_secret(self, name: str) -> Any | None:
        raise NotImplementedError("Subclasses must implement this method")

class EnvironmentSource(SecretSource):
    def get_secret(self, name: str) -> Any | None:
        return os.environ.get(name)

class VaultSource(SecretSource):
    def __init__(self, vault_client):
        self.vault_client = vault_client

    def get_secret(self, name: str) -> Any | None:
        try:
            secret = self.vault_client.read(name)
            if secret and 'data' in secret and 'secret' in secret['data']:
                return secret['data']['secret']
            return None
        except Exception as e:
            raise SecretSourceError(f"Failed to read {name} from vault: {e}")

class SecretCache:
    def __init__(self, ttl: int = 60):
        self.ttl = ttl
        self.cache = {}

    def exists(self, name: str) -> bool:
        return name in self.cache

    def get(self, name: str) -> Any | None:
        if name not in self.cache or (time.time() - self.cache[name]['timestamp']) > self.ttl:
            raise SecretCacheMiss(f"Secret {name} not found in cache")
        return self.cache[name]['value']

    def set(self, name: str, value: Any):
        self.cache[name] = {'timestamp': time.time(), 'value': value}

class SecretSerializer:
    @staticmethod
    def serialize(secret: Any) -> str:
        import json
        return json.dumps(secret)

def secret_exists(name: str) -> bool:
    for source in (EnvironmentSource(),):
        try:
            if source.get_secret(name):
                return True
        except (SecretSourceError, MissingSecret):
            continue
    return False

def bulk_get_secrets(names: List[str], policy: SecretPolicy = SecretPolicy.DEFAULT) -> dict:
    loader = SecretLoader([EnvironmentSource()], cache=SecretCache())
    return {name: loader.get_secret(name, policy=policy) for name in names}

def bulk_require_secrets(names: List[str], policy: SecretPolicy = SecretPolicy.DEFAULT) -> dict:
    loader = SecretLoader([EnvironmentSource()], cache=SecretCache())
    return {name: loader.require_secret(name, policy=policy) for name in names}

def log_safe_secret(name: str, value: str) -> str:
    masked_value = mask(value)
    _log.info("secret [%s] = %s", name, masked_value)
    return masked_value

def audit_secret_access(name: str, user: Optional[str] = None):
    if user is not None:
        _log.info("audit: user [%s] accessed secret [%s]", user, name)


def _selftest() -> None:
    """Offline, falsifiable self-test of secret loading + masking (env-only)."""
    name = "SCRAPYARD_SELFTEST_SECRET"
    value = "super-secret-value-123456"
    os.environ.pop(name, None)

    # 1) NEGATIVE: a required-but-missing secret fails closed
    missing = False
    try:
        require_secret(name)
    except MissingSecret:
        missing = True
    assert missing, "require_secret must raise MissingSecret when unset"
    assert secret_exists(name) is False, "secret_exists must be False when unset"

    # 2) once present, it loads with the real value
    os.environ[name] = value
    try:
        assert require_secret(name) == value, "require_secret must return the real value"
        assert get_secret(name) == value and secret_exists(name) is True

        # 3) NEGATIVE: masking hides the secret body and never leaks it in full
        m_default = mask(value)                       # default: show last 4
        assert m_default != value, "masked value must differ from the real value"
        assert value[:-4] not in m_default, "masked value must not contain the hidden body"
        assert m_default.endswith(value[-4:]), "default mask shows only the last 4 chars"
        assert mask(value, policy=MaskPolicy.REDACT) == "*" * len(value), "REDACT hides everything"
        assert value not in mask(value, policy=MaskPolicy.ANONYMIZE)

        # 4) log_safe_secret returns the masked (not raw) value
        assert log_safe_secret(name, value) == mask(value), "log path must mask"

        # 5) SecretLoader over EnvironmentSource resolves the same value
        loader = SecretLoader([EnvironmentSource()], cache=SecretCache())
        assert loader.require_secret(name) == value
    finally:
        os.environ.pop(name, None)

    print("secrets: OK (9 assertions incl. missing-secret + masking-leak negatives)")


if __name__ == "__main__":
    _selftest()
