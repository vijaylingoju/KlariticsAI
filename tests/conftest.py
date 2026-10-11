"""Shared fixtures: settings, the app, an HTTP client, and two event stores.

- `store_path` / `service`: the full seeded store (20,000 users, 60 days), built
  once and cached under `.cache/` keyed by a hash of the seeding code, so a
  rerun reuses it and a change to the seeder rebuilds it.
- `tiny_service`: a hand-written store small enough to compute every expected
  answer by hand.
"""

import hashlib
from collections.abc import AsyncIterator, Iterator
from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp.server.mcpserver import MCPServer

from app.analytics import store as store_module
from app.analytics.service import AnalyticsService
from app.analytics.store import DatasetInfo, connect_read_only, create_schema, write_meta
from app.core.config import Settings
from app.main import create_app
from app.mcp_server.server import build_server
from app.seed import generator, scenarios
from app.seed.generator import seed

ROOT = Path(__file__).resolve().parent.parent


def _seed_fingerprint() -> str:
    digest = hashlib.sha256()
    for module in (generator, scenarios, store_module):
        digest.update(Path(str(module.__file__)).read_bytes())
    return digest.hexdigest()[:16]


@pytest.fixture(scope="session")
def store_path() -> Path:
    """The full seeded store, rebuilt only when the seeding code changes."""
    path = ROOT / ".cache" / f"store-{_seed_fingerprint()}" / "klaritics.duckdb"
    if not path.is_file():
        seed(path)
    return path


@pytest.fixture(scope="session")
def service(store_path: Path) -> Iterator[AnalyticsService]:
    """Analytics over the full seeded store."""
    con = connect_read_only(store_path)
    yield AnalyticsService(con)
    con.close()


# Hand-written store. Four users on 2026-01-01..2026-01-10.
#   u1 Android/BR/phone/organic   v1: signup d1; views d1 10:00; cart d1 10:05; checkout d1 10:10;
#                                     purchase d1 10:20; session d2 and d8
#   u2 iOS/US/tablet/tiktok_ads   v1: signup d1; views d1 11:00; cart d2 12:00 (after 24h window);
#                                     session d2
#   u3 Android/US/phone/organic   v2: signup d2; views d2; cart d2; checkout d2; no purchase;
#                                     session d9
#   u4 Android/BR/phone/referral  v2: signup d3; session d4; views d5
TINY_START = date(2026, 1, 1)
TINY_END = date(2026, 1, 10)
TINY_USERS = [
    ("u1", "2026-01-01 09:00", "Android", "BR", "phone", "organic", "1.0.0"),
    ("u2", "2026-01-01 09:30", "iOS", "US", "tablet", "tiktok_ads", "1.0.0"),
    ("u3", "2026-01-02 09:00", "Android", "US", "phone", "organic", "2.0.0"),
    ("u4", "2026-01-03 09:00", "Android", "BR", "phone", "referral", "2.0.0"),
]
TINY_EVENTS = [
    ("u1", "signup", "2026-01-01 09:00"),
    ("u1", "session_start", "2026-01-01 09:00"),
    ("u1", "product_viewed", "2026-01-01 10:00"),
    ("u1", "add_to_cart", "2026-01-01 10:05"),
    ("u1", "checkout_started", "2026-01-01 10:10"),
    ("u1", "purchase_completed", "2026-01-01 10:20"),
    ("u1", "session_start", "2026-01-02 08:00"),
    ("u1", "session_start", "2026-01-08 08:00"),
    ("u2", "signup", "2026-01-01 09:30"),
    ("u2", "session_start", "2026-01-01 09:30"),
    ("u2", "product_viewed", "2026-01-01 11:00"),
    ("u2", "session_start", "2026-01-02 12:00"),
    ("u2", "add_to_cart", "2026-01-02 12:00"),
    ("u3", "signup", "2026-01-02 09:00"),
    ("u3", "session_start", "2026-01-02 09:00"),
    ("u3", "product_viewed", "2026-01-02 09:10"),
    ("u3", "product_viewed", "2026-01-02 09:12"),
    ("u3", "add_to_cart", "2026-01-02 09:15"),
    ("u3", "checkout_started", "2026-01-02 09:20"),
    ("u3", "session_start", "2026-01-09 09:00"),
    ("u4", "signup", "2026-01-03 09:00"),
    ("u4", "session_start", "2026-01-03 09:00"),
    ("u4", "session_start", "2026-01-04 09:00"),
    ("u4", "product_viewed", "2026-01-05 09:00"),
]


def build_tiny_store(path: Path) -> None:
    """Write the hand-written store to `path`."""
    users = {u[0]: u for u in TINY_USERS}
    con = duckdb.connect(str(path))
    try:
        create_schema(con)
        for user_id, signup, os, country, device, source, version in TINY_USERS:
            con.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)",
                [user_id, datetime.fromisoformat(signup), os, country, device, source, version],
            )
        for i, (user_id, name, ts) in enumerate(TINY_EVENTS, start=1):
            _, _, os, country, device, source, version = users[user_id]
            con.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    i,
                    user_id,
                    name,
                    datetime.fromisoformat(ts),
                    version,
                    os,
                    country,
                    device,
                    source,
                ],
            )
        write_meta(con, DatasetInfo(start=TINY_START, end=TINY_END, seed=0))
    finally:
        con.close()


@pytest.fixture(scope="session")
def tiny_store_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The hand-written store on disk."""
    path = tmp_path_factory.mktemp("tiny") / "tiny.duckdb"
    build_tiny_store(path)
    return path


@pytest.fixture(scope="session")
def tiny_service(tiny_store_path: Path) -> Iterator[AnalyticsService]:
    """Analytics over the hand-written store."""
    con = connect_read_only(tiny_store_path)
    yield AnalyticsService(con)
    con.close()


@pytest.fixture(scope="session")
def server(service: AnalyticsService) -> MCPServer:
    """The MCP server over the full store."""
    return build_server(service)


@pytest.fixture
def settings(store_path: Path, tmp_path: Path) -> Settings:
    """Test settings, independent of any .env file; model calls replay, files go to tmp."""
    return Settings(
        _env_file=None,
        env="test",
        log_format="console",
        store_path=store_path,
        llm_mode="replay",
        llm_recordings_dir=tmp_path / "recordings",
        llm_ledger_path=tmp_path / "ledger.jsonl",
        reports_dir=tmp_path / "reports",
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    """The application with its lifespan run, so `app.state` is populated."""
    application = create_app(settings)
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client bound to the app in memory."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
