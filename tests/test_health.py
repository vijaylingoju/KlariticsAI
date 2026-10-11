"""Health routes and the request-id contract."""

from pathlib import Path

from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import __version__
from app.api.health.router import get_readiness_check
from app.core.config import Settings
from app.main import create_app


async def test_healthz_reports_version(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_request_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/healthz", headers={"x-request-id": "abc-123"})

    assert response.headers["x-request-id"] == "abc-123"


async def test_request_id_is_minted_when_missing(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert len(response.headers["x-request-id"]) == 32


async def test_readyz_ok_when_store_answers(app: FastAPI, client: AsyncClient) -> None:
    async def healthy() -> None:
        return None

    app.dependency_overrides[get_readiness_check] = lambda: healthy

    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"store": "ok"}}


async def test_readyz_503_when_store_is_down(app: FastAPI, client: AsyncClient) -> None:
    async def down() -> None:
        raise FileNotFoundError("store missing")

    app.dependency_overrides[get_readiness_check] = lambda: down

    response = await client.get("/readyz", headers={"x-request-id": "r-1"})

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "service_unavailable"
    assert body["error"]["details"] == {"store": "failed"}
    assert body["error"]["request_id"] == "r-1"


async def test_readyz_ok_against_the_real_store(client: AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["checks"] == {"store": "ok"}


async def test_readyz_503_when_the_store_file_is_missing(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None, env="test", log_format="console", store_path=tmp_path / "none.duckdb"
    )
    application = create_app(settings)

    async with (
        LifespanManager(application),
        AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as http,
    ):
        response = await http.get("/readyz")

    assert response.status_code == 503
