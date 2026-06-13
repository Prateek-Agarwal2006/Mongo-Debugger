from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    cursor_api_key: str | None = None
    cursor_model: str = "composer-2.5"
    phase2_investigation_max_tool_calls: int = 6
    phase2_rca_max_tool_calls: int = 6
    phase2_max_clarifying_questions: int = 10
    graylog_api_url: str | None = None
    graylog_api_token: str | None = None
    graylog_auth_mode: str = "token"
    graylog_default_query: str = "source:mongod OR mongodb OR mongo"
    graylog_search_limit: int = 50
    graph_padding_minutes: int = 30
    grafana_url: str = "http://localhost:3030"
    ftdc_api_url: str = "http://localhost:5408"
    ftdc_load_timeout_seconds: int = 300
    grafana_startup_wait_seconds: int = 240


@lru_cache
def get_settings() -> Settings:
    return Settings()
