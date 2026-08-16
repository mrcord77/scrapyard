"""
settings — Application settings, loaded from the environment with safe defaults.

### PART-META-JSON
{
  "name": "settings",
  "layer": "runtime",
  "purpose": "Runtime settings dataclass for generated apps loaded from env vars (DATABASE_URL, APP_ENV, LOG_LEVEL/LOG_JSON, DEBUG, field/PQ encryption keys) with fail-fast production checks: no sqlite fallback outside development and mandatory PQ field keys when the app requires encryption at rest.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Environment variables at process start.",
  "outputs": "An immutable-by-convention Settings dataclass consumed by bootstrap/init_database.",
  "files_created": [],
  "security_notes": "load_settings refuses to default DATABASE_URL to a local sqlite file outside development, and with require_encryption=True refuses to boot without PQ_FIELD_PUBLIC/PQ_FIELD_SECRET — missing key material is a startup error, not a silent plaintext fallback. Settings hold credentials (database DSN, encryption keys); never log the full dataclass.",
  "ai_usage": "settings = load_settings(); pass to init_database/bootstrap; branch on settings.dev.",
  "example": "s = load_settings(); engine = init_database(s, Base)",
  "import_path": "scrapyard.runtime.settings"
}
### END-PART-META
"""
from __future__ import annotations

STATUS = "core"

import os
from typing import Optional
from dataclasses import dataclass

@dataclass
class Settings:
    database_url: str = "sqlite:///./app.db"
    app_env: str = "development"
    log_level: str = "INFO"
    log_json: bool = False
    debug: bool = False
    field_encryption_key: Optional[str] = None
    pq_field_public: Optional[str] = None
    pq_field_secret: Optional[str] = None
    require_encryption: bool = False

    @property
    def dev(self) -> bool:
        return self.app_env == "development"


def load_settings(*, require_encryption: bool = False) -> Settings:
    """Read settings from env. Fail fast on unsafe production configuration."""
    app_env = os.environ.get("APP_ENV", "development")
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        if app_env == "development":
            db_url = "sqlite:///./app.db"  # dev convenience only
        else:
            raise RuntimeError(
                "DATABASE_URL is required in non-development environments "
                "(refusing to fall back to a local sqlite file in production)."
            )
    s = Settings(
        database_url=db_url,
        app_env=app_env,
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        log_json=os.environ.get("LOG_JSON", "0") in ("1", "true", "True"),
        debug=os.environ.get("DEBUG", "0") in ("1", "true", "True"),
        field_encryption_key=os.environ.get("FIELD_ENCRYPTION_KEY"),
        pq_field_public=os.environ.get("PQ_FIELD_PUBLIC"),
        pq_field_secret=os.environ.get("PQ_FIELD_SECRET"),
        require_encryption=require_encryption,
    )
    if require_encryption and not (s.pq_field_public and s.pq_field_secret):
        raise RuntimeError(
            "PQ_FIELD_PUBLIC and PQ_FIELD_SECRET are required (this app encrypts "
            "sensitive fields at rest under hybrid post-quantum key transport). "
            'Mint a keypair: python -c "from scrapyard.security.pq_field_encryption '
            'import generate_recipient_hex; print(generate_recipient_hex())" and set '
            "PQ_FIELD_PUBLIC / PQ_FIELD_SECRET (or hand custody to citadel)."
        )
    return s


def _selftest() -> None:
    keys = ("APP_ENV", "DATABASE_URL", "LOG_LEVEL", "LOG_JSON", "DEBUG",
            "FIELD_ENCRYPTION_KEY", "PQ_FIELD_PUBLIC", "PQ_FIELD_SECRET")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ.pop(k, None)

        # dev defaults
        s = load_settings()
        assert s.dev and s.app_env == "development"
        assert s.database_url == "sqlite:///./app.db"
        assert s.log_level == "INFO" and s.log_json is False and s.debug is False

        # env is honoured
        os.environ.update({"LOG_LEVEL": "DEBUG", "LOG_JSON": "1", "DEBUG": "true",
                           "DATABASE_URL": "postgresql://db/app"})
        s = load_settings()
        assert s.log_level == "DEBUG" and s.log_json and s.debug
        assert s.database_url == "postgresql://db/app"

        # production without DATABASE_URL refuses the sqlite fallback
        os.environ["APP_ENV"] = "production"
        os.environ.pop("DATABASE_URL", None)
        try:
            load_settings()
            raise AssertionError("prod sqlite fallback allowed")
        except RuntimeError as e:
            assert "DATABASE_URL" in str(e)
        os.environ["DATABASE_URL"] = "postgresql://db/app"
        assert not load_settings().dev

        # require_encryption demands PQ keys
        try:
            load_settings(require_encryption=True)
            raise AssertionError("missing PQ keys accepted")
        except RuntimeError as e:
            assert "PQ_FIELD_PUBLIC" in str(e)
        os.environ["PQ_FIELD_PUBLIC"] = "aa" * 32
        os.environ["PQ_FIELD_SECRET"] = "bb" * 32
        s = load_settings(require_encryption=True)
        assert s.require_encryption and s.pq_field_public == "aa" * 32
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print("runtime.settings selftest: PASS")


if __name__ == "__main__":
    _selftest()
