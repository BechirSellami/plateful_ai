from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://plateful:plateful@localhost:5432/plateful"

    # Anthropic
    anthropic_api_key: str = ""

    # Mem0 Cloud
    mem0_api_key: str = ""

    # App
    app_env: str = "development"
    log_level: str = "INFO"


settings = Settings()
