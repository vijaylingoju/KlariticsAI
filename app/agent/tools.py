"""Run MCP tool calls for one question, inside the call budget, and log every one.

The agent and the fallback both go through `ToolRunner`, so the bound of
eight calls per question holds whoever is calling, and the log is complete:
every call, its arguments, its result or error, and who made it.
"""

import json
import time
from typing import Any, Literal

from mcp_types import TextContent
from pydantic import BaseModel

from mcp import Client

MAX_TOOL_CALLS = 8

Caller = Literal["agent", "fallback", "plan"]


class ToolCallRecord(BaseModel):
    """One call as it happened."""

    index: int
    caller: Caller
    tool: str
    arguments: dict[str, Any]
    ok: bool
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    duration_ms: int


class BudgetSpentError(Exception):
    """The question has used all its tool calls."""


class ToolRunner:
    """Calls tools on an open MCP client and records them."""

    def __init__(self, client: Client, limit: int = MAX_TOOL_CALLS) -> None:
        self.client = client
        self.limit = limit
        self.log: list[ToolCallRecord] = []

    @property
    def remaining(self) -> int:
        """Calls left for this question."""
        return self.limit - len(self.log)

    async def call(self, tool: str, arguments: dict[str, Any], caller: Caller) -> ToolCallRecord:
        """Run one tool; a tool error is recorded, not raised."""
        if self.remaining <= 0:
            raise BudgetSpentError(f"all {self.limit} tool calls used")
        started = time.monotonic()
        result = await self.client.call_tool(tool, arguments)
        duration_ms = int((time.monotonic() - started) * 1000)
        record: ToolCallRecord
        if result.is_error:
            text = next((b.text for b in result.content if isinstance(b, TextContent)), "")
            try:
                error = json.loads(text)
            except json.JSONDecodeError:
                error = {"code": "invalid_arguments", "message": text[:500]}
            record = ToolCallRecord(
                index=len(self.log) + 1,
                caller=caller,
                tool=tool,
                arguments=arguments,
                ok=False,
                error=error if isinstance(error, dict) else {"message": str(error)},
                duration_ms=duration_ms,
            )
        else:
            structured = result.structured_content
            record = ToolCallRecord(
                index=len(self.log) + 1,
                caller=caller,
                tool=tool,
                arguments=arguments,
                ok=True,
                result=structured if isinstance(structured, dict) else {"result": structured},
                duration_ms=duration_ms,
            )
        self.log.append(record)
        return record


def _round(value: object) -> object:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


SEGMENT_KEYS = (
    "dimension",
    "segment",
    "baseline_value",
    "current_value",
    "contribution",
    "share_of_change",
    "explained",
    "separation_z",
    "likely_cause",
)


def compact(record: ToolCallRecord) -> str:
    """The result as the model reads it: what matters for the next step, few tokens."""
    if not record.ok:
        return json.dumps({"error": record.error})
    result = record.result or {}
    if record.tool == "compare_segments":
        view = {
            "baseline": result.get("baseline", {}).get("value"),
            "current": result.get("current", {}).get("value"),
            "change": result.get("change"),
            "relative_change": result.get("relative_change"),
            "explained_by_top_segment": {
                b["dimension"]: b["explained_by_top_segment"] for b in result.get("breakdowns", [])
            },
            "top_contributors": [
                {k: s.get(k) for k in SEGMENT_KEYS} for s in result.get("top_contributors", [])
            ],
        }
        return json.dumps(_round(view), separators=(",", ":"))
    if record.tool == "list_events":
        view = {
            "events": [e["name"] for e in result.get("events", [])],
            "dimensions": {d["name"]: d["values"] for d in result.get("dimensions", [])},
            "range": [result.get("dataset_start"), result.get("dataset_end")],
        }
        return json.dumps(view, separators=(",", ":"))
    if isinstance(result.get("series"), list) and len(result["series"]) > 31:
        result = {**result, "series": result["series"][-31:], "series_truncated": True}
    return json.dumps(_round(result), separators=(",", ":"))
