"""Application configuration loaded from environment variables.

All sensitive values (SECRET_KEY, DATABASE_URL, API keys) MUST be provided
via environment variables or a .env file. The app will refuse to start
without them. See .env.example for the full list.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULTS = frozenset({
    "change-me-to-a-random-string-at-least-32-chars",
    "change-me-in-production-use-a-real-secret",
    "",
})


class Settings(BaseSettings):
    """Central configuration. Values come from .env or environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "ai-analyst-api"
    app_version: str = "0.1.0"
    debug: bool = False

    # Security — no defaults, must be set explicitly
    secret_key: str
    database_url: str
    redis_url: str

    # LLM
    llm_default_provider: Literal[
        "anthropic", "openai", "gemini", "groq"
    ] = "anthropic"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-pro"

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # File upload limits
    max_file_size_mb: int = 500
    max_total_upload_mb: int = 1024
    max_files_per_upload: int = 10
    max_tables_per_dataset: int = 20

    # Storage
    storage_dir: str = "./storage"

    # CORS
    cors_origins: str = '["http://localhost:5173","http://localhost:3000"]'

    # JWT
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # Pipeline timeouts
    pipeline_timeout_seconds: int = 600
    agent_default_timeout_seconds: int = 300

    # LLM retry with exponential backoff
    llm_max_retries: int = 3
    llm_retry_base_seconds: float = 1.0
    llm_retry_max_seconds: float = 60.0

    # Rate limiting
    rate_limit_default: str = "60/minute"
    rate_limit_heavy: str = "10/minute"

    @field_validator("secret_key")
    @classmethod
    def _reject_insecure_secret(cls, v: str) -> str:
        if v in _INSECURE_DEFAULTS:
            print(
                "FATAL: SECRET_KEY is missing or uses a known placeholder. "
                "Set a strong random value in your .env file. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\"",
                file=sys.stderr,
            )
            raise ValueError("SECRET_KEY must be set to a secure random value")
        if len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters"
            )
        return v

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def max_total_upload_bytes(self) -> int:
        return self.max_total_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return json.loads(self.cors_origins)

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
