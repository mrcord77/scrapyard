"""
config — Typed settings loaded from env/.env with validation.

### PART-META-JSON
{
  "name": "config",
  "layer": "foundation",
  "purpose": "Typed application settings on pydantic v2 / pydantic-settings: env + .env loading with multi-path search, cached get_settings() with production secret enforcement, validation hooks, default-value overrides, extra-field policy control, and nested settings validation.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "pydantic",
    "pydantic-settings"
  ],
  "inputs": "Environment variables, optional .env files, programmatic defaults/hooks.",
  "outputs": "Validated Settings instances (cached via get_settings).",
  "files_created": [],
  "security_notes": "get_settings() hard-fails when environment=production while secret_key still holds the shipped placeholder, so a default secret cannot silently reach prod. Settings values may include credentials (secret_key, database_url); never log a full settings dump outside development. .env files are read with extra='ignore' by default so unexpected keys cannot inject fields unless the policy is explicitly loosened.",
  "ai_usage": "from scrapyard.foundation.config import get_settings; settings = get_settings() — call it everywhere, it is cached.",
  "example": "settings = get_settings(); engine = create_engine(settings.database_url)",
  "import_path": "scrapyard.foundation.config"
}
### END-PART-META
"""
from __future__ import annotations

import os
import sys
from typing import Any, Callable, Dict, List, Optional, cast

from pydantic import BaseModel, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

STATUS = "core"


class ConfigurableEnvironment(BaseModel):
    paths: Optional[List[str]] = None
    encoding: str = "utf-8"
    extra_policy: str = "ignore"
    validation_hooks: List[Callable[[BaseModel], None]] = []
    default_values: Dict[str, Any] = {}
    cache_maxsize: int = 128


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "scrapyard-app"
    environment: str = "development"   # development | staging | production
    debug: bool = False
    secret_key: str = "change-me-in-prod"
    database_url: str = "sqlite:///./app.db"
    log_level: str = "INFO"
    log_json: bool = False

    @property
    def is_prod(self) -> bool:
        return self.environment == "production"


# --- module-level configuration state ---
_validation_hooks: List[Callable[[Settings], None]] = []
_default_overrides: Dict[str, Any] = {}
_cache_maxsize: int = 128
_settings_cache: Optional[Settings] = None


def load_env_from_paths(paths: Optional[List[str]] = None) -> Settings:
    """Load Settings using the first existing .env file among ``paths``
    (each path is a directory expected to contain a '.env'). Falls back to
    plain env-var loading when none exists."""
    for path in paths or []:
        env_file = os.path.join(path, ".env")
        if os.path.isfile(env_file):
            return cast(Settings, Settings(_env_file=env_file))
    return Settings()


def set_env_vars_from_dict(config: Dict[str, str]) -> None:
    for key, value in config.items():
        os.environ[key] = value


def validate_secrets(settings: Settings) -> List[str]:
    """Return a list of human-readable secret-validation problems (empty = OK)."""
    errors: List[str] = []
    if settings.secret_key == "change-me-in-prod" and settings.is_prod:
        errors.append("SECRET_KEY must be set in production")
    if settings.is_prod and len(settings.secret_key) < 16:
        errors.append("SECRET_KEY must be at least 16 characters in production")
    return errors


def get_log_level(settings: Settings) -> str:
    """Effective log level: an explicitly configured log_level wins; otherwise
    a per-environment default applies."""
    env_defaults = {"production": "INFO", "staging": "DEBUG", "development": "DEBUG"}
    if settings.log_level and settings.log_level != Settings.model_fields["log_level"].default:
        return settings.log_level
    return env_defaults.get(settings.environment, settings.log_level or "INFO")


def set_env_file_encoding(encoding: str = "utf-8") -> None:
    """Change the .env encoding used by subsequently constructed Settings."""
    Settings.model_config["env_file_encoding"] = encoding


def set_extra_field_policy(policy: str = "ignore") -> None:
    """Set how unexpected fields are treated: 'ignore', 'allow', or 'forbid'
    ('raise' is accepted as a legacy alias for 'forbid')."""
    aliases = {"raise": "forbid"}
    policy = aliases.get(policy, policy)
    if policy not in ("ignore", "allow", "forbid"):
        raise ValueError(f"Invalid extra field policy: {policy}")
    Settings.model_config["extra"] = policy
    Settings.model_rebuild(force=True)  # pydantic v2 bakes config into the schema
    clear_settings_cache()


def add_validation_hook(hook: Callable[[Settings], None]) -> None:
    """Register a hook invoked (with the Settings instance) by get_settings()."""
    if not callable(hook):
        raise TypeError("hook must be callable")
    _validation_hooks.append(hook)


def clear_validation_hooks() -> None:
    _validation_hooks.clear()


def set_default_values(defaults: Dict[str, Any]) -> None:
    """Override defaults for known Settings fields. Environment variables still
    win; overrides apply only when the variable is absent from the env."""
    for key in defaults:
        if key not in Settings.model_fields:
            raise AttributeError(f"Invalid default key: {key}")
    _default_overrides.update(defaults)
    clear_settings_cache()


def set_cache_maxsize(maxsize: int = 128) -> None:
    """Set the settings-cache size (>=0). 0 disables caching entirely."""
    global _cache_maxsize
    if maxsize < 0:
        raise ValueError("maxsize must be >= 0")
    _cache_maxsize = maxsize
    clear_settings_cache()


def clear_settings_cache() -> None:
    global _settings_cache
    _settings_cache = None


def get_settings() -> Settings:
    """Construct (and cache) validated Settings; enforces prod secret hygiene
    and runs registered validation hooks."""
    global _settings_cache
    if _settings_cache is not None and _cache_maxsize > 0:
        return _settings_cache
    kwargs = {k: v for k, v in _default_overrides.items()
              if k.upper() not in os.environ and k not in os.environ}
    s = cast(Settings, Settings(**kwargs))
    if s.is_prod and s.secret_key == "change-me-in-prod":
        raise RuntimeError("SECRET_KEY must be set in production")
    for hook in _validation_hooks:
        hook(s)
    if _cache_maxsize > 0:
        _settings_cache = s
    return s


class NestedSettings(BaseModel):
    auth: Dict[str, str] = {}
    database: Dict[str, str] = {}

    @model_validator(mode="before")
    @classmethod
    def validate_nested(cls, values: Any) -> Any:
        if isinstance(values, dict):
            for key in cls.model_fields.keys():
                if key in values and values[key] is not None and not isinstance(values[key], dict):
                    raise ValueError(f"Invalid nested config structure for {key}")
        return values

    @field_validator("auth", "database", mode="before")
    @classmethod
    def ensure_dict(cls, v: Any) -> Dict[str, str]:
        if v is None:
            return {}
        return cast(Dict[str, str], v)


def _selftest() -> None:
    saved_env = {k: os.environ.get(k) for k in
                 ("APP_NAME", "ENVIRONMENT", "SECRET_KEY", "LOG_LEVEL", "DEBUG")}
    try:
        for k in saved_env:
            os.environ.pop(k, None)
        clear_settings_cache()
        clear_validation_hooks()
        _default_overrides.clear()

        # defaults load and cache
        s = get_settings()
        assert s.app_name == "scrapyard-app" and not s.is_prod
        assert get_settings() is s  # cached

        # env vars are picked up after cache clear
        os.environ["APP_NAME"] = "cfg-test"
        clear_settings_cache()
        assert get_settings().app_name == "cfg-test"

        # prod + placeholder secret is fatal
        os.environ["ENVIRONMENT"] = "production"
        clear_settings_cache()
        try:
            get_settings()
            raise AssertionError("prod placeholder secret accepted")
        except RuntimeError:
            pass
        os.environ["SECRET_KEY"] = "a-real-secret-of-decent-length"
        clear_settings_cache()
        assert get_settings().is_prod

        # validate_secrets returns messages, not broken ValidationError objects
        bad = Settings(environment="production", secret_key="change-me-in-prod")
        msgs = validate_secrets(bad)
        assert any("SECRET_KEY" in m for m in msgs)
        assert validate_secrets(Settings(environment="development")) == []

        # log level resolution
        assert get_log_level(Settings(log_level="ERROR")) == "ERROR"
        assert get_log_level(Settings(environment="staging")) == "DEBUG"
        assert get_log_level(Settings(environment="production")) == "INFO"

        # hooks run on construction
        os.environ.pop("ENVIRONMENT", None)
        os.environ.pop("SECRET_KEY", None)
        seen: list = []
        add_validation_hook(lambda st: seen.append(st.app_name))
        clear_settings_cache()
        get_settings()
        assert seen == ["cfg-test"]
        clear_validation_hooks()

        # default overrides: env absent -> override wins; env present -> env wins
        os.environ.pop("APP_NAME", None)
        set_default_values({"app_name": "overridden"})
        assert get_settings().app_name == "overridden"
        os.environ["APP_NAME"] = "from-env"
        clear_settings_cache()
        assert get_settings().app_name == "from-env"
        try:
            set_default_values({"not_a_field": 1})
            raise AssertionError("unknown default key accepted")
        except AttributeError:
            pass
        _default_overrides.clear()

        # extra-field policy (v2 values + legacy alias)
        set_extra_field_policy("forbid")
        try:
            Settings(bogus_field="x")
            raise AssertionError("extra field accepted under forbid")
        except ValidationError:
            pass
        set_extra_field_policy("raise")  # legacy alias
        assert Settings.model_config["extra"] == "forbid"
        set_extra_field_policy("ignore")
        try:
            set_extra_field_policy("warn")
            raise AssertionError("invalid policy accepted")
        except ValueError:
            pass

        # cache disable
        set_cache_maxsize(0)
        a, b = get_settings(), get_settings()
        assert a is not b
        set_cache_maxsize(128)

        # env-file loading from a path list (first existing wins; missing skipped)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            envdir = os.path.join(tmp, "real")
            os.makedirs(envdir)
            with open(os.path.join(envdir, ".env"), "w", encoding="utf-8") as f:
                f.write("APP_NAME=dotenv-app\n")
            os.environ.pop("APP_NAME", None)
            s2 = load_env_from_paths([os.path.join(tmp, "missing"), envdir])
            assert s2.app_name == "dotenv-app"
            assert load_env_from_paths([]).app_name == "scrapyard-app"

        # set_env_vars_from_dict + encoding setter
        set_env_vars_from_dict({"CFG_SELFTEST_MARK": "1"})
        assert os.environ["CFG_SELFTEST_MARK"] == "1"
        os.environ.pop("CFG_SELFTEST_MARK", None)
        set_env_file_encoding("utf-8")

        # NestedSettings on v2 validators
        n = NestedSettings(auth={"provider": "oidc"}, database=None)
        assert n.database == {} and n.auth["provider"] == "oidc"
        try:
            NestedSettings(auth="not-a-dict")
            raise AssertionError("bad nested structure accepted")
        except ValidationError:
            pass
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        clear_settings_cache()
        clear_validation_hooks()
        _default_overrides.clear()

    print("config selftest: PASS")


if __name__ == "__main__":
    _selftest()
