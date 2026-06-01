"""Configuration loading.

Non-secret application settings come from a YAML file (CONFIG_PATH, default
./config.yaml). Secrets come from environment variables so the same image can
run on Digital Ocean App Platform with encrypted env vars.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class WorkingGroup:
    name: str
    archive_url: str


@dataclass(frozen=True)
class Topic:
    name: str
    description: str = ""
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModelPricing:
    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True)
class LLMConfig:
    model_summarization: str
    model_categorization: str
    use_batch_api: bool
    pricing: dict[str, ModelPricing]


@dataclass(frozen=True)
class ProcessingConfig:
    active_threshold_days: int
    reprocess_on_new_messages: bool
    pre_filter_admin_messages: bool
    draft_metadata_refresh_days: int
    budget_usd: float


@dataclass(frozen=True)
class DraftsConfig:
    datatracker_api_base: str
    fetch_metadata_on_first_reference: bool
    weekly_refresh_active_drafts: bool


@dataclass(frozen=True)
class IngestionConfig:
    request_timeout_seconds: int = 30
    max_retries: int = 4
    backoff_base_seconds: int = 2


@dataclass(frozen=True)
class Settings:
    working_groups: list[WorkingGroup]
    topics: list[Topic]
    llm: LLMConfig
    processing: ProcessingConfig
    drafts: DraftsConfig
    ingestion: IngestionConfig

    # secrets / env
    database_url: str
    anthropic_api_key: str | None
    session_secret: str
    log_level: str
    public_base_url: str

    def wg_by_name(self, name: str) -> WorkingGroup | None:
        return next((w for w in self.working_groups if w.name == name), None)


def _normalize_database_url(url: str) -> str:
    """SQLAlchemy needs a driver-qualified scheme; DO/Heroku hand out postgres://."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found at {path}. Set CONFIG_PATH or create config.yaml."
        )
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    config_path = Path(os.environ.get("CONFIG_PATH", "config.yaml"))
    raw = _load_yaml(config_path)

    wgs = [WorkingGroup(**w) for w in raw.get("working_groups", [])]
    topics = [Topic(**t) for t in raw.get("topics", [])]

    llm_raw = raw.get("llm", {})
    pricing = {
        model: ModelPricing(**vals) for model, vals in (llm_raw.get("pricing") or {}).items()
    }
    llm = LLMConfig(
        model_summarization=llm_raw.get("model_summarization", "claude-sonnet-4-6"),
        model_categorization=llm_raw.get("model_categorization", "claude-haiku-4-5"),
        use_batch_api=bool(llm_raw.get("use_batch_api", True)),
        pricing=pricing,
    )

    proc_raw = raw.get("processing", {})
    processing = ProcessingConfig(
        active_threshold_days=int(proc_raw.get("active_threshold_days", 90)),
        reprocess_on_new_messages=bool(proc_raw.get("reprocess_on_new_messages", True)),
        pre_filter_admin_messages=bool(proc_raw.get("pre_filter_admin_messages", True)),
        draft_metadata_refresh_days=int(proc_raw.get("draft_metadata_refresh_days", 30)),
        budget_usd=float(proc_raw.get("budget_usd", 200.0)),
    )

    drafts_raw = raw.get("drafts", {})
    drafts = DraftsConfig(
        datatracker_api_base=drafts_raw.get(
            "datatracker_api_base", "https://datatracker.ietf.org/api/v1/"
        ),
        fetch_metadata_on_first_reference=bool(
            drafts_raw.get("fetch_metadata_on_first_reference", True)
        ),
        weekly_refresh_active_drafts=bool(drafts_raw.get("weekly_refresh_active_drafts", True)),
    )

    ing_raw = raw.get("ingestion", {})
    ingestion = IngestionConfig(
        request_timeout_seconds=int(ing_raw.get("request_timeout_seconds", 30)),
        max_retries=int(ing_raw.get("max_retries", 4)),
        backoff_base_seconds=int(ing_raw.get("backoff_base_seconds", 2)),
    )

    database_url = _normalize_database_url(
        os.environ.get("DATABASE_URL", "postgresql+psycopg://wg:wg@localhost:5432/wgtracker")
    )

    return Settings(
        working_groups=wgs,
        topics=topics,
        llm=llm,
        processing=processing,
        drafts=drafts,
        ingestion=ingestion,
        database_url=database_url,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        session_secret=os.environ.get("SESSION_SECRET", "dev-insecure-session-secret"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        public_base_url=os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
    )


def reload_settings() -> Settings:
    """Clear the cache (used by tests and after config edits)."""
    get_settings.cache_clear()
    return get_settings()
