"""Ask the analyst; save, fetch, render and re-run reports.

Saving happens only on the server, from an answer the analyst just produced
(`save: true`), so a client cannot store numbers the tools never returned.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agent.analyst import Analyst, Answer
from app.core.errors import NotFoundError, ServiceUnavailableError
from app.reports.render import markdown, page
from app.reports.rerun import RerunResult, rerun
from app.reports.store import ReportNotFoundError, ReportStore, ReportSummary

router = APIRouter(prefix="/v1", tags=["analyst"])


class QuestionIn(BaseModel):
    """A question in plain language."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=500)
    save: bool = Field(False, description="Save the answer as a report and return its id.")


def get_analyst(request: Request) -> Analyst:
    """The analyst the lifespan built; 503 when the event store is missing."""
    analyst: Analyst | None = getattr(request.app.state, "analyst", None)
    if analyst is None:
        raise ServiceUnavailableError("analyst unavailable: the event store is not loaded")
    return analyst


def get_reports(request: Request) -> ReportStore:
    """The report store."""
    store: ReportStore = request.app.state.reports
    return store


def _load(store: ReportStore, report_id: str) -> Answer:
    try:
        return store.get(report_id)
    except ReportNotFoundError as exc:
        raise NotFoundError("report not found", details={"id": report_id}) from exc


@router.post("/questions", response_model=Answer)
async def ask(
    body: QuestionIn,
    analyst: Annotated[Analyst, Depends(get_analyst)],
    store: Annotated[ReportStore, Depends(get_reports)],
) -> Answer:
    """Answer a question; with `save`, store it as a report."""
    answer = await analyst.ask(body.question)
    return store.save(answer) if body.save else answer


@router.get("/reports", response_model=list[ReportSummary])
async def list_reports(store: Annotated[ReportStore, Depends(get_reports)]) -> list[ReportSummary]:
    """Saved reports, newest first."""
    return store.list()


@router.get("/reports/{report_id}", response_model=Answer)
async def get_report(report_id: str, store: Annotated[ReportStore, Depends(get_reports)]) -> Answer:
    """A saved report as JSON."""
    return _load(store, report_id)


@router.get("/reports/{report_id}/markdown", response_class=PlainTextResponse)
async def get_report_markdown(
    report_id: str, store: Annotated[ReportStore, Depends(get_reports)]
) -> str:
    """A saved report as Markdown."""
    return markdown(_load(store, report_id))


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
async def get_report_html(
    report_id: str, store: Annotated[ReportStore, Depends(get_reports)]
) -> str:
    """A saved report as a standalone HTML page."""
    return page(_load(store, report_id))


@router.post("/reports/{report_id}/rerun", response_model=RerunResult)
async def rerun_report(
    report_id: str,
    analyst: Annotated[Analyst, Depends(get_analyst)],
    store: Annotated[ReportStore, Depends(get_reports)],
) -> RerunResult:
    """Re-run the report's tool calls and say whether every number reproduces."""
    return await rerun(_load(store, report_id), analyst.target)
