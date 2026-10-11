"""The `klaritics-analytics` MCP server: five read-only analytics tools.

Descriptions are written for a model reader: what the tool returns, when to use
it and when not to. Every tool is read-only and idempotent, annotated so hosts
can auto-approve it. Errors come back as tool errors whose text is a JSON
object with `code`, `message`, `retryable` and `details`.

Run locally over stdio with `make mcp`, or over streamable HTTP (bearer token
required) with `make mcp-http`.
"""

import json
from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal

import structlog
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.analytics.catalog import Dimension
from app.analytics.errors import AnalyticsError
from app.analytics.models import (
    CompareQuery,
    CompareResult,
    CountQuery,
    CountResult,
    DateRange,
    EventCatalog,
    Filters,
    FunnelQuery,
    FunnelResult,
    Measure,
    Metric,
    RetentionQuery,
    RetentionResult,
)
from app.analytics.service import AnalyticsService

log = structlog.get_logger()

INSTRUCTIONS = (
    "Product analytics over a seeded Klaritics event dataset. Call list_events first to learn "
    "the tracked events, the dimensions and the dataset's date range. To explain why a metric "
    "changed, use compare_segments: it returns the change and ranks segments by how much of it "
    "they explain. An event that list_events does not return is not tracked."
)

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

Event = Annotated[str, Field(description="Tracked event name exactly as list_events returns it.")]
Day = Annotated[date, Field(description="A calendar day, YYYY-MM-DD, inside the dataset range.")]
GroupBy = Annotated[Dimension | None, Field(description="Split results by this dimension.")]


async def _call(name: str, fn: Callable[[], BaseModel]) -> CallToolResult:
    """Run a blocking query off the event loop; an analytics error becomes a tool error
    whose text is exactly the error's JSON, so a model can parse `code` and act on it."""
    try:
        result = await run_in_threadpool(fn)
    except AnalyticsError as exc:
        log.info("tool refused", tool=name, code=exc.code)
        text = json.dumps(exc.as_dict(), default=str)
        return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)
    log.info("tool ok", tool=name)
    data = result.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data))], structured_content=data
    )


def build_server(service: AnalyticsService) -> MCPServer:
    """The server with its five tools bound to one analytics service."""
    server = MCPServer(
        name="klaritics-analytics",
        title="Klaritics analytics",
        instructions=INSTRUCTIONS,
        version=__version__,
    )

    @server.tool(
        title="List tracked events",
        description=(
            "Returns every tracked event (name, meaning, volume), every segment dimension with "
            "all its values, and the dataset's first and last day. Call it first; use it to map "
            "the user's words (for example 'orders' or 'bought') to event names. An event it "
            "does not list is not tracked."
        ),
        annotations=READ_ONLY,
    )
    async def list_events() -> Annotated[CallToolResult, EventCatalog]:
        return await _call("list_events", service.list_events)

    @server.tool(
        title="Count events",
        description=(
            "Counts one event between two days: occurrences or unique users, as a total, a daily "
            "or weekly series, or split by one dimension. Use for volume questions (how many "
            "signups, did purchases rise). Not for rates: use funnel or retention."
        ),
        annotations=READ_ONLY,
    )
    async def count_events(
        event: Event,
        start: Day,
        end: Day,
        measure: Measure = "events",
        interval: Annotated[
            Literal["total", "day", "week"], Field(description="Total or a series.")
        ] = "total",
        filters: Filters | None = None,
        group_by: GroupBy = None,
    ) -> Annotated[CallToolResult, CountResult]:
        query = CountQuery.model_validate(
            {
                "event": event,
                "start": start,
                "end": end,
                "measure": measure,
                "interval": interval,
                "filters": filters or {},
                "group_by": group_by,
            }
        )
        return await _call("count_events", lambda: service.count_events(query))

    @server.tool(
        title="Funnel conversion",
        description=(
            "Ordered conversion through 2 to 6 events for users whose first step falls between "
            "two days; each later step must follow within window_hours of the first. Returns "
            "users per step and conversion rates (0 to 1), optionally per segment. Use for "
            "checkout or purchase conversion."
        ),
        annotations=READ_ONLY,
    )
    async def funnel(
        steps: Annotated[
            list[str], Field(min_length=2, max_length=6, description="Event names in order.")
        ],
        start: Day,
        end: Day,
        window_hours: Annotated[
            int, Field(ge=1, le=336, description="Conversion window in hours.")
        ] = 24,
        filters: Filters | None = None,
        group_by: GroupBy = None,
    ) -> Annotated[CallToolResult, FunnelResult]:
        query = FunnelQuery(
            steps=steps,
            start=start,
            end=end,
            window_hours=window_hours,
            filters=filters or {},
            group_by=group_by,
        )
        return await _call("funnel", lambda: service.funnel(query))

    @server.tool(
        title="Retention",
        description=(
            "Day-N retention (0 to 1) of users whose first start_event (default signup) falls in "
            "the cohort range: the share who do return_event (default session_start) exactly N "
            "days later. The cohort must end at least N days before the dataset's last day."
        ),
        annotations=READ_ONLY,
    )
    async def retention(
        cohort_start: Day,
        cohort_end: Day,
        days: Annotated[
            list[int], Field(min_length=1, max_length=4, description="N values, 1 to 30.")
        ] = [1, 7],  # noqa: B006 - pydantic copies defaults
        start_event: Event = "signup",
        return_event: Event = "session_start",
        filters: Filters | None = None,
        group_by: GroupBy = None,
    ) -> Annotated[CallToolResult, RetentionResult]:
        query = RetentionQuery(
            cohort_start=cohort_start,
            cohort_end=cohort_end,
            days=days,
            start_event=start_event,
            return_event=return_event,
            filters=filters or {},
            group_by=group_by,
        )
        return await _call("retention", lambda: service.retention(query))

    @server.tool(
        title="Compare segments",
        description=(
            "Explains a change. Computes a metric (count, conversion or retention) in a current "
            "and a baseline period, the change, and for every value of each dimension its "
            "contribution, "
            "`explained` (share of the change that vanishes without it) and `separation_z`. "
            "`top_contributors` lists likely causes first. Use it to find which segment is "
            "responsible for a drop or a lift."
        ),
        annotations=READ_ONLY,
    )
    async def compare_segments(
        metric: Metric,
        current: DateRange,
        baseline: DateRange,
        dimensions: Annotated[
            list[Dimension] | None, Field(description="Default: all five.")
        ] = None,
        filters: Filters | None = None,
        top_n: Annotated[int, Field(ge=1, le=20)] = 5,
    ) -> Annotated[CallToolResult, CompareResult]:
        payload: dict[str, object] = {
            "metric": metric,
            "current": current,
            "baseline": baseline,
            "filters": filters or {},
            "top_n": top_n,
        }
        if dimensions:
            payload["dimensions"] = dimensions
        query = CompareQuery.model_validate(payload)
        return await _call("compare_segments", lambda: service.compare_segments(query))

    return server
