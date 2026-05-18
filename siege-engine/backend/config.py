import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///data/siege_engine.db"

    # Auth
    jwt_secret_key: str = "CHANGE-ME-IN-PRODUCTION"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 720  # 30 days

    # Git
    git_repos_base_path: str = "data/repos"

    # LLM
    anthropic_api_key: str = ""
    default_model: str = "claude-opus-4-6"
    default_temperature: float = 0.3

    # Rate Limiting
    max_concurrent_llm_calls: int = 1
    llm_retry_max_attempts: int = 3
    llm_retry_base_delay: float = 1.0

    # Claude CLI
    cli_timeout: int = 1800  # 30 min default for CLI invocations

    # GitHub OAuth
    github_client_id: str = ""
    github_client_secret: str = ""
    # Optional explicit OAuth redirect URI. Defaults to
    # `cors_origins[0] + "/github/callback"` when unset, which is the
    # right shape for a single-origin deploy. Set explicitly when CORS
    # carries multiple origins (e.g. a droplet IP + a friendly
    # hostname) and the OAuth app is registered against the friendly
    # one.
    github_redirect_uri: str = ""

    # Server
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_file": ".env", "env_prefix": "SIEGE_"}


settings = Settings()

# Fallback: accept ANTHROPIC_API_KEY directly from environment
if not settings.anthropic_api_key:
    settings.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
