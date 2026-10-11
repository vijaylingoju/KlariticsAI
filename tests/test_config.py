"""Settings fail fast and name the problem."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.env == "development"
    assert settings.port == 8080
    assert settings.log_level == "info"
    assert settings.log_format == "json"
    assert settings.store_path == Path("data/klaritics.duckdb")
    assert settings.mcp_http_token is None


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("STORE_PATH", "/data/other.duckdb")

    settings = Settings(_env_file=None)

    assert settings.log_level == "debug"
    assert settings.port == 9000
    assert settings.store_path == Path("/data/other.duckdb")


def test_mcp_token_is_kept_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_HTTP_TOKEN", "s3cret")

    settings = Settings(_env_file=None)

    assert settings.mcp_http_token is not None
    assert settings.mcp_http_token.get_secret_value() == "s3cret"
    assert "s3cret" not in repr(settings)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("LOG_LEVEL", "loud"),
        ("ENV", "staging"),
        ("PORT", "eighty"),
        ("MCP_HTTP_PORT", "eighty"),
    ],
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError, match=variable.lower()):
        Settings(_env_file=None)
