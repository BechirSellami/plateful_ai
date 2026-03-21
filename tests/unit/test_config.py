import pytest

from plateful.core.config import Settings


@pytest.mark.unit
class TestSettings:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear env vars that CI sets so we test actual defaults
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
        )
        assert s.app_env == "development"
        assert s.log_level == "INFO"
        assert "plateful" in s.database_url

    def test_custom_values(self) -> None:
        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
            app_env="test",
            log_level="DEBUG",
            anthropic_api_key="sk-test",
        )
        assert s.app_env == "test"
        assert s.anthropic_api_key == "sk-test"
