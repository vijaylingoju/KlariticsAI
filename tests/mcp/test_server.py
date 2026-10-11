"""The MCP server over the protocol: every tool listed, annotated and called (US-02-006).

Calls go through a real MCP client connected in-process to the server, over
the hand-written store, so the JSON a model sees is what is asserted.
Test ids trace to docs/testing/test-cases.md.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, TextContent

from app.analytics.service import AnalyticsService
from app.mcp_server.auth import BearerTokenMiddleware
from app.mcp_server.server import build_server
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]
TOOLS = {"list_events", "count_events", "funnel", "retention", "compare_segments"}

VALID_CALLS: dict[str, dict[str, Any]] = {
    "list_events": {},
    "count_events": {
        "event": "signup",
        "start": "2026-01-01",
        "end": "2026-01-10",
        "group_by": "country",
    },
    "funnel": {
        "steps": ["product_viewed", "add_to_cart"],
        "start": "2026-01-01",
        "end": "2026-01-10",
    },
    "retention": {"cohort_start": "2026-01-01", "cohort_end": "2026-01-02", "days": [1]},
    "compare_segments": {
        "metric": {"kind": "count", "event": "session_start"},
        "current": {"start": "2026-01-02", "end": "2026-01-10"},
        "baseline": {"start": "2026-01-01", "end": "2026-01-01"},
        "dimensions": ["country"],
    },
}


@pytest.fixture
def server(tiny_service: AnalyticsService) -> MCPServer:
    """The server over the hand-written store. Each test opens its own client: the
    client's task group must open and close in the test's own task."""
    return build_server(tiny_service)


def _error(result: CallToolResult) -> dict[str, Any]:
    assert result.is_error
    block = result.content[0]
    assert isinstance(block, TextContent)
    payload: dict[str, Any] = json.loads(block.text)
    return payload


async def test_tc0060_server_lists_five_read_only_annotated_tools(server: MCPServer) -> None:
    async with Client(server) as client:
        listed = await client.list_tools()

    tools = {t.name: t for t in listed.tools}
    annotated = {
        name
        for name, t in tools.items()
        if t.annotations is not None
        and t.annotations.read_only_hint is True
        and t.annotations.destructive_hint is False
        and t.annotations.idempotent_hint is True
        and t.annotations.open_world_hint is False
        and t.description
        and t.output_schema
    }
    sys.stderr.write(
        f"mcp-tools: {len(tools)} exposed, {len(VALID_CALLS)} tested, {len(annotated)} annotated\n"
    )
    assert set(tools) == TOOLS == set(VALID_CALLS) == annotated


@pytest.mark.parametrize("name", sorted(VALID_CALLS))
async def test_tc0061_every_tool_answers_a_valid_call_with_structured_content(
    server: MCPServer, name: str
) -> None:
    async with Client(server) as client:
        result = await client.call_tool(name, VALID_CALLS[name])

    assert not result.is_error
    assert isinstance(result.structured_content, dict)


async def test_tc0062_untracked_event_returns_a_not_tracked_tool_error(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "count_events", {"event": "refund", "start": "2026-01-01", "end": "2026-01-10"}
        )

    error = _error(result)
    assert error["code"] == "not_tracked"
    assert error["retryable"] is False
    assert "refund" in error["message"]


async def test_tc0063_dates_outside_the_data_return_a_typed_error(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "count_events", {"event": "signup", "start": "2025-01-01", "end": "2026-01-10"}
        )

    error = _error(result)
    assert error["code"] == "invalid_date_range"
    assert error["details"]["dataset_start"] == "2026-01-01"


async def test_tc0064_unknown_argument_is_rejected_by_the_schema(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "funnel", {"steps": ["signup"], "start": "2026-01-01", "end": "2026-01-10"}
        )

    assert result.is_error


async def test_tc0065_count_tool_returns_the_same_numbers_as_the_service(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.call_tool("count_events", VALID_CALLS["count_events"])

    assert result.structured_content is not None
    groups = {g["segment"]: g["value"] for g in result.structured_content["groups"]}
    assert (result.structured_content["total"], groups) == (4, {"BR": 2, "US": 2})


@pytest.mark.parametrize(
    ("headers", "allowed"),
    [
        ({}, False),
        ({"Authorization": "Bearer wrong"}, False),
        ({"Authorization": "Bearer s3cret"}, True),
    ],
    ids=["missing", "wrong", "valid"],
)
async def test_tc0066_http_transport_requires_the_bearer_token(
    tiny_service: AnalyticsService, headers: dict[str, str], allowed: bool
) -> None:
    app = build_server(tiny_service).streamable_http_app()
    app.add_middleware(BearerTokenMiddleware, token="s3cret")

    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as http,
    ):
        response = await http.get("/mcp", headers=headers)

    assert (response.status_code != 401) is allowed


async def test_tc0067_stdio_transport_serves_the_tools(tiny_store_path: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server", "--transport", "stdio"],
        env={**os.environ, "STORE_PATH": str(tiny_store_path), "LOG_FORMAT": "json"},
        cwd=str(ROOT),
    )

    async with Client(params) as client:
        result = await client.call_tool("count_events", VALID_CALLS["count_events"])

    assert result.structured_content is not None
    assert result.structured_content["total"] == 4
