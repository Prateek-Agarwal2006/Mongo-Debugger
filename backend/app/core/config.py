from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_root: Path | None = None
    database_url: str | None = None
    worker_id: str | None = None
    cursor_api_key: str | None = None
    cursor_model: str = "grok-4.5"
    llm_provider: str = "cursor"
    google_api_key: str | None = None
    daytona_api_key: str | None = None
    google_model: str = "gemini-2.5-flash"
    google_genai_use_vertexai: bool = False
    phase2_investigation_max_tool_calls: int = 1_000_000
    phase2_rca_max_tool_calls: int = 1_000_000
    phase2_max_clarifying_questions: int = 10
    phase2_chatbot_max_tool_calls: int = 1_000_000
    phase2_chatbot_max_replay_messages: int = 12
    phase2_chatbot_max_attachment_bytes: int = 524_288
    phase2_web_fetch_max_bytes: int = 24_000
    phase2_web_fetch_timeout_s: int = 20
    phase2_web_allowlist_suffixes: str | None = None
    graylog_api_url: str | None = None
    graylog_api_token: str | None = None
    graylog_auth_mode: str = "token"
    graylog_default_query: str = "source:mongod OR mongodb OR mongo"
    graylog_search_limit: int = 50
    graph_padding_minutes: int = 30
    pipeline_worker_poll_seconds: float = 2.0
    grafana_url: str = "http://localhost:3030"


@lru_cache
def get_settings() -> Settings:
    return Settings()
