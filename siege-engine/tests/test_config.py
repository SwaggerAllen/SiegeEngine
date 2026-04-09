"""Tests for backend.config – settings and defaults."""

from backend.config import Settings, settings


class TestSettings:
    def test_default_database_url(self):
        s = Settings()
        assert "sqlite" in s.database_url

    def test_default_jwt_algorithm(self):
        assert settings.jwt_algorithm == "HS256"

    def test_default_jwt_expiry(self):
        assert settings.jwt_expiry_hours == 720

    def test_default_model(self):
        assert "claude" in settings.default_model

    def test_default_temperature(self):
        assert 0 <= settings.default_temperature <= 1

    def test_max_concurrent_llm_calls_positive(self):
        assert settings.max_concurrent_llm_calls > 0

    def test_retry_config(self):
        assert settings.llm_retry_max_attempts >= 1
        assert settings.llm_retry_base_delay > 0

    def test_cors_origins_is_list(self):
        assert isinstance(settings.cors_origins, list)
        assert len(settings.cors_origins) > 0

    def test_cli_timeouts_positive(self):
        assert settings.cli_timeout_document > 0
        assert settings.cli_timeout_code > 0

    def test_env_prefix(self):
        assert Settings.model_config["env_prefix"] == "SIEGE_"
