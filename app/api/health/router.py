"""Liveness and readiness. Readiness checks every dependency the service needs."""

from collections.abc import Awaitable, Callable
from typing import Annotated

import duckdb
import structlog
from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.analytics.service import AnalyticsService
from app.api.health.schemas import HealthOut, ReadyOut
from app.core.errors import ErrorEnvelope, ServiceUnavailableError

log = structlog.get_logger()
router = APIRouter(tags=["health"])

ReadinessCheck = Callable[[], Awaitable[None]]


def get_version(request: Request) -> str:
    """The application version, as a dependency so tests can pin it."""
    version: str = request.app.version
    return version


def get_readiness_check(request: Request) -> ReadinessCheck:
    """A trivial query against the event store the lifespan opened."""
    service: AnalyticsService | None = getattr(request.app.state, "analytics", None)

    async def check() -> None:
        if service is None:
            raise FileNotFoundError("event store not loaded")
        await run_in_threadpool(service.ping)

    return check


@router.get("/healthz", response_model=HealthOut)
async def healthz(version: Annotated[str, Depends(get_version)]) -> HealthOut:
    """The process is up and serving."""
    return HealthOut(status="ok", version=version)


@router.get("/readyz", response_model=ReadyOut, responses={503: {"model": ErrorEnvelope}})
async def readyz(check: Annotated[ReadinessCheck, Depends(get_readiness_check)]) -> ReadyOut:
    """Every dependency is reachable; 503 with the failed check otherwise."""
    try:
        await check()
    except (OSError, TimeoutError, duckdb.Error) as exc:
        log.warning("readiness failed", check="store", error_type=type(exc).__name__)
        raise ServiceUnavailableError(
            "event store unavailable", details={"store": "failed"}
        ) from exc
    return ReadyOut(status="ok", checks={"store": "ok"})
