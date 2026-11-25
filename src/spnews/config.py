"""Application configuration via environment variables (.env supported)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PostgreSQL 18 + pgvector
    spnews_database_url: str = Field(
        default="postgresql://spnews@127.0.0.1:5432/spnews",
        alias="SPNEWS_DATABASE_URL",
    )

    # Chat LLM (OpenAI-compatible)
    llm_base_url: str = Field(default="https://api.deepseek.com", alias="LLM_BASE_URL")
    llm_model: str = Field(default="deepseek-flash", alias="LLM_MODEL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    deepseek_api_key: str | None = Field(default=None, alias="DEEPSEEK_API_KEY")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")

    # Embedding API (OpenRouter qwen/qwen3-embedding-8b -> MRL 1024d)
    embed_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="EMBED_BASE_URL"
    )
    embed_model: str = Field(
        default="qwen/qwen3-embedding-8b", alias="EMBED_MODEL"
    )
    embed_api_key: str | None = Field(default=None, alias="EMBED_API_KEY")
    embed_dim: int = Field(default=1024, alias="EMBED_DIM")

    # Site & timezone
    timezone: str = Field(default="America/Chicago", alias="TIMEZONE")
    site_url: str = Field(default="https://sports.yhao.dev", alias="SITE_URL")
    cloudflare_api_token: str | None = Field(default=None, alias="CLOUDFLARE_API_TOKEN")
    cloudflare_account_id: str | None = Field(default=None, alias="CLOUDFLARE_ACCOUNT_ID")
    cf_pages_project: str = Field(default="spnews", alias="CF_PAGES_PROJECT")
    rss_fetch_days: int = Field(default=2, alias="RSS_FETCH_DAYS")
    report_lookback_hours: int = Field(default=48, alias="REPORT_LOOKBACK_HOURS")
    memory_days: int = Field(default=14, alias="MEMORY_DAYS")
    micro_cluster_threshold: float = Field(default=0.72, alias="MICRO_CLUSTER_THRESHOLD")
    memory_sim_threshold: float = Field(default=0.55, alias="MEMORY_SIM_THRESHOLD")
    max_events_per_sport: int = Field(default=12, alias="MAX_EVENTS_PER_SPORT")
    max_high_per_sport: int = Field(default=3, alias="MAX_HIGH_PER_SPORT")
    max_enrich_per_event: int = Field(default=3, alias="MAX_ENRICH_PER_EVENT")
    llm_concurrency: int = Field(default=14, alias="LLM_CONCURRENCY")
    http_concurrency: int = Field(default=10, alias="HTTP_CONCURRENCY")

    def resolved_llm_api_key(self) -> str:
        """Select API key matching the configured LLM_BASE_URL."""
        base = self.llm_base_url.lower()
        if "openrouter.ai" in base:
            key = self.openrouter_api_key or self.llm_api_key
        elif "deepseek.com" in base:
            key = self.deepseek_api_key or self.llm_api_key
        else:
            key = self.llm_api_key or self.deepseek_api_key or self.openrouter_api_key
        if not key:
            raise ValueError(
                f"Missing API key for LLM_BASE_URL={self.llm_base_url}. "
                "Set LLM_API_KEY, DEEPSEEK_API_KEY, or OPENROUTER_API_KEY in .env."
            )
        return key

    def resolved_embed_api_key(self) -> str:
        """Select API key for the embedding endpoint."""
        key = self.embed_api_key or self.openrouter_api_key
        if not key:
            raise ValueError(
                f"Missing API key for EMBED_BASE_URL={self.embed_base_url}. "
                "Set EMBED_API_KEY or OPENROUTER_API_KEY in .env."
            )
        return key


def get_settings() -> Settings:
    return Settings()
