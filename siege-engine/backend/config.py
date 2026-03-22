import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///data/siege_engine.db"

    # Auth
    jwt_secret_key: str = "CHANGE-ME-IN-PRODUCTION"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # Git
    git_repos_base_path: str = "data/repos"

    # LLM
    anthropic_api_key: str = ""
    default_model: str = "claude-sonnet-4-20250514"
    default_temperature: float = 0.3

    # Rate Limiting
    max_concurrent_llm_calls: int = 1
    llm_retry_max_attempts: int = 3
    llm_retry_base_delay: float = 1.0

    # Claude CLI
    cli_timeout_document: int = 600  # 10 min for document stages
    cli_timeout_code: int = 1800  # 30 min for code gen/review
    cli_max_turns_code: int = 25  # Unused directly — CLI manages turns via budget
    cli_max_budget_code: float = 5.0  # Max USD per code gen/review invocation

    # GitHub OAuth
    github_client_id: str = ""
    github_client_secret: str = ""

    # Server
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {"env_file": ".env", "env_prefix": "SIEGE_"}


settings = Settings()

# Fallback: accept ANTHROPIC_API_KEY directly from environment
if not settings.anthropic_api_key:
    settings.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
