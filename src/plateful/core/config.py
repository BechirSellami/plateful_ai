from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to the project root (3 levels up from this file)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

# Pre-load .env so we can fill in values that the shell sets to empty.
# Claude Desktop exports ANTHROPIC_API_KEY="" which overrides the real
# key from .env when pydantic-settings gives env vars higher priority.
_dotenv_values: dict[str, str | None] = dotenv_values(str(_ENV_FILE)) if _ENV_FILE.exists() else {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://plateful:plateful@localhost:5432/plateful"

    # Anthropic
    anthropic_api_key: str = ""

    # Mem0 Cloud
    mem0_api_key: str = ""

    # Langfuse (observability)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    def model_post_init(self, __context: Any) -> None:
        """Fill in fields that the shell env set to empty but .env has a value for."""
        for field_name in self.model_fields:
            current = getattr(self, field_name)
            env_key = field_name.upper()
            if current == "" and env_key in _dotenv_values:
                dotenv_val = _dotenv_values[env_key]
                if dotenv_val:
                    object.__setattr__(self, field_name, dotenv_val)


settings = Settings()
