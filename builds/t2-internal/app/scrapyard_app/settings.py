"""Generated settings (env-driven)."""
from __future__ import annotations
import os

class Settings:
    def __init__(self):
        self.app_env = os.environ.get("APP_ENV", "development")
        self.database_url = os.environ.get("DATABASE_URL", "sqlite:///./app.db")
        self.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

settings = Settings()
