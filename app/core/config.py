"""Process configuration from the environment.

Construction fails fast and names every invalid variable at once. Secrets
have no defaults. `get_settings` is the one module-level singleton.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Env = Literal["development", "test", "production"]
LogLevel = Literal["debug", "info", "warning", "error"]
LogFormat = Literal["json", "console"]


class Settings(BaseSettings):
    """Validated process configuration, read from the environment and .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "KlariticsAI"
    env: Env = "development"
    port: int = 8080
    log_level: LogLevel = "info"
    log_format: LogFormat = "json"
    # The seeded event store (read-only at runtime) and where it is built.
    store_path: Path = Path("data/klaritics.duckdb")
    # Bearer token for the MCP server's HTTP transport; HTTP refuses to start without it.
    mcp_http_token: SecretStr | None = None
    mcp_http_port: int = 8090
    # Model calls: live calls OpenRouter, record also saves each answer, replay
    # serves saved answers only (tests and CI; no key, no network).
    llm_mode: Literal["live", "record", "replay"] = "live"
    openrouter_api_key: SecretStr | None = None
    llm_recordings_dir: Path = Path("evals/recordings")
    llm_ledger_path: Path = Path("data/llm_ledger.jsonl")
    llm_budget_usd: float = Field(8.0, gt=0)
    # Saved reports.
    reports_dir: Path = Path("data/reports")


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""
    return Settings()
