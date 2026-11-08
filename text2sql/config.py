"""Konfigurasi dari environment variable / file .env."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_model: str = "openai:gpt-6-luna"
    openai_api_key: str | None = None
    # none | low | medium | high. Kosong = tidak dikirim.
    llm_reasoning_effort: str | None = "low"

    # Database
    schema_sql_path: Path = PROJECT_ROOT / "schema.sql"
    sqlite_db_path: Path = PROJECT_ROOT / "data" / "southcity.db"
    sql_dialect: str = "sqlite"

    # Guardrails
    max_sql_retries: int = 3  # soal meminta minimal 2x retry
    max_result_rows: int = 200
    query_timeout_seconds: float = 5.0

    # None = tanggal sistem. Diisi saat testing agar "hari ini" deterministik.
    today_override: date | None = None

    def today(self) -> date:
        return self.today_override or date.today()


@lru_cache
def get_settings() -> Settings:
    return Settings()
