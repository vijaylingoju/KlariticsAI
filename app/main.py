"""Application factory for KlariticsAI.

Wiring only: settings, logging, tracing, middleware, exception handlers,
routers and the lifespan that opens the event store. Run with
`uvicorn app.main:create_app --factory` locally; the image runs gunicorn
with uvicorn workers against the same factory.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app import __version__
from app.agent.analyst import Analyst
from app.analytics.service import AnalyticsService
from app.analytics.store import connect_read_only
from app.api.analyst.router import router as analyst_router
from app.api.health.router import router as health_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware
from app.core.telemetry import configure_tracing
from app.llm.gateway import Gateway, build_provider, killed_features
from app.llm.ledger import Ledger
from app.llm.providers import ReplayProvider
from app.mcp_server.server import build_server
from app.reports.store import ReportStore

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the event store read-only, build the analyst over it, close on shutdown.

    A missing store does not stop the process: liveness stays up, readiness
    reports the store as failed and the analyst answers 503 until it is seeded.
    """
    settings: Settings = app.state.settings
    con = None
    app.state.analytics = None
    app.state.analyst = None
    app.state.reports = ReportStore(settings.reports_dir)
    try:
        con = connect_read_only(settings.store_path)
    except (FileNotFoundError, LookupError) as exc:
        log.warning("store unavailable", path=str(settings.store_path), error=str(exc))
    if con is not None:
        service = AnalyticsService(con)
        key = (
            settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else None
        )
        gateway = Gateway(
            build_provider(settings.llm_mode, key, ReplayProvider(settings.llm_recordings_dir)),
            Ledger(settings.llm_ledger_path, settings.llm_budget_usd),
            disabled=killed_features(),
        )
        app.state.analytics = service
        app.state.analyst = Analyst(build_server(service), gateway)
    log.info("startup", env=settings.env, version=__version__, llm_mode=settings.llm_mode)
    try:
        yield
    finally:
        if con is not None:
            con.close()
        log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application. Tests pass explicit settings."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    docs_enabled = settings.env != "production"
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(analyst_router)
    configure_tracing(app, settings.app_name, __version__)
    return app
