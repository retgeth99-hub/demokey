from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import BeforeValidator, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_database_url(value: str) -> str:
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


DatabaseUrl = Annotated[str, BeforeValidator(_normalize_database_url)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "PubMed 科研情报分析 API"
    app_env: str = "demo"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: DatabaseUrl = "postgresql+asyncpg://pubmed:pubmed@localhost:5432/pubmed_demo"

    ncbi_api_key: str | None = None
    ncbi_tool: str = "pubmed-insight-demo"
    ncbi_email: str = "replace@example.com"
    ncbi_rate_limit: float = Field(default=8.0, gt=0, le=10)
    ncbi_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    service_api_key: str | None = None
    cors_origins: list[str] = []
    analysis_cache_hours: int = Field(default=24, ge=0, le=720)
    raw_retention_days: int = Field(default=30, ge=1, le=365)
    worker_enabled: bool = True
    worker_concurrency: int = Field(default=1, ge=1, le=2)
    worker_poll_seconds: float = Field(default=1.0, ge=0.2, le=60)
    worker_lease_seconds: int = Field(default=90, ge=30, le=900)
    log_level: str = "INFO"

    @field_validator("ncbi_api_key", "deepseek_api_key", "service_api_key", mode="before")
    @classmethod
    def empty_secret_to_none(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()

