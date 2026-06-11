"""
RecoverFlow AI — Application Configuration
============================================
Loads all secrets and connection strings from environment variables
using Pydantic Settings for validation and type safety.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Central configuration loaded from environment or .env file."""

    # ── Application ──────────────────────────────────────────
    APP_NAME: str = "RecoverFlow AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    MAINTENANCE_MODE: bool = False

    # ── Database (PostgreSQL) ────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://recoverflow:recoverflow@db:5432/recoverflow"

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Converts the async URL to a synchronous psycopg2 URL for Celery."""
        return self.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")

    # ── Redis / Celery ───────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/1"

    # ── Shopify ──────────────────────────────────────────────
    SHOPIFY_API_KEY: str = ""          # Also known as Client ID
    SHOPIFY_API_SECRET: str = ""       # Used to verify JWT & webhook HMAC
    BACKEND_API_SECRET: str = "default_local_secret"  # Shared secret to authenticate Remix webhook forwarding

    # ── Google Gemini ────────────────────────────────────────
    GEMINI_API_KEY: str = ""

    # ── Meta WhatsApp Cloud API (fallback defaults) ──────────
    WHATSAPP_DEFAULT_ACCESS_TOKEN: str = ""
    WHATSAPP_DEFAULT_PHONE_NUMBER_ID: str = ""

    # ── Recovery Timing Defaults (seconds) ───────────────────
    RECOVERY_STEP_1_DELAY: int = 15      # 15 seconds
    RECOVERY_STEP_2_DELAY: int = 21600     # 6 hours
    RECOVERY_STEP_3_DELAY: int = 86400     # 24 hours

    # ── Credits ──────────────────────────────────────────────
    FREE_SEED_CREDITS: int = 50            # Seeded on first install

    # ── CORS ─────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["*"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Cached singleton — avoids re-parsing env on every request."""
    return Settings()
