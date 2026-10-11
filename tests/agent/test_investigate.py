"""The bounded investigation and its fallback, over the real MCP server (US-04-002, US-04-003)."""

from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from app.agent.intent import Intent, IntentDraft, resolve_intent
from app.agent.investigate import compare_arguments, investigate
from app.agent.tools import MAX_TOOL_CALLS, ToolRunner
from app.analytics.models import EventCatalog
from app.analytics.service import AnalyticsService
from app.llm.types import ProviderUnavailableError
from mcp import Client
from tests.agent.conftest import FUNNEL_DRAFT, QUIET_DRAFT, RETENTION_DRAFT, ScriptedLLM, Step


@pytest.fixture(scope="module")
def catalog(service: AnalyticsService) -> EventCatalog:
    return service.list_events()


def _intent(draft: dict[str, Any], catalog: EventCatalog) -> Intent:
    return resolve_intent("why?", IntentDraft.model_validate(draft), catalog)


def _finish(dimension: str | None, segment: str | None) -> Step:
    return [("finish", {"dimension": dimension, "segment": segment, "reasoning": "r"})]


async def _run(server: MCPServer, intent: Intent, llm: ScriptedLLM) -> tuple[Any, ToolRunner]:
    async with Client(server) as client:
        runner = ToolRunner(client)
        finding = await investigate(intent, runner, llm)
    return finding, runner


async def test_tc0220_agent_conclusion_backed_by_evidence_is_accepted(
    server: MCPServer, catalog: EventCatalog
) -> None:
    intent = _intent(FUNNEL_DRAFT, catalog)
    llm = ScriptedLLM(
        [],
        steps=[[("compare_segments", compare_arguments(intent))], _finish("app_version", "5.4.0")],
    )

    finding, runner = await _run(server, intent, llm)

    assert (finding.concluded_by, finding.cause["segment"]) == ("agent", "5.4.0")
    assert finding.evidence_call == 1
    assert [c.caller for c in runner.log] == ["agent"]


async def test_tc0221_agent_may_drill_further_before_finishing(
    server: MCPServer, catalog: EventCatalog
) -> None:
    intent = _intent(RETENTION_DRAFT, catalog)
    drill = {
        "cohort_start": "2026-09-17",
        "cohort_end": "2026-09-23",
        "days": [7],
        "filters": {"os": ["Android"]},
        "group_by": "country",
    }
    llm = ScriptedLLM(
        [],
        steps=[
            [("compare_segments", compare_arguments(intent))],
            [("retention", drill)],
            _finish("country", "BR"),
        ],
    )

    finding, runner = await _run(server, intent, llm)

    assert (finding.concluded_by, finding.cause["segment"]) == ("agent", "BR")
    assert [c.tool for c in runner.log] == ["compare_segments", "retention"]


@pytest.mark.parametrize(
    ("steps", "reason"),
    [
        ("finish_only", "no comparison across dimensions"),
        ("compare_then_wrong", "which the evidence does not mark"),
        ("compare_then_null", "named no cause although the evidence marks one"),
        ("no_calls", "stopped without calling finish"),
    ],
    ids=["cause_without_drilling", "unsupported_cause", "missed_cause", "no_finish"],
)
async def test_tc0222_unbacked_conclusion_falls_back_to_contributions(
    server: MCPServer, catalog: EventCatalog, steps: str, reason: str
) -> None:
    intent = _intent(FUNNEL_DRAFT, catalog)
    compare: Step = [("compare_segments", compare_arguments(intent))]
    scripts: dict[str, list[Step]] = {
        "finish_only": [_finish("app_version", "5.4.0")],
        "compare_then_wrong": [compare, _finish("os", "Android")],
        "compare_then_null": [compare, _finish(None, None)],
        "no_calls": [[]],
    }
    script = scripts[steps]

    finding, _ = await _run(server, intent, ScriptedLLM([], steps=script))

    assert finding.concluded_by == "fallback"
    assert reason in (finding.fallback_reason or "")
    assert (finding.cause["dimension"], finding.cause["segment"]) == ("app_version", "5.4.0")


async def test_tc0223_tool_calls_never_exceed_eight(
    server: MCPServer, catalog: EventCatalog
) -> None:
    intent = _intent(FUNNEL_DRAFT, catalog)
    count = ("count_events", {"event": "signup", "start": "2026-09-01", "end": "2026-09-30"})
    llm = ScriptedLLM([], steps=[[count, count, count]] * 6)

    finding, runner = await _run(server, intent, llm)

    assert len(runner.log) <= MAX_TOOL_CALLS
    assert [c.caller for c in runner.log].count("agent") == 7
    assert runner.log[-1].caller == "fallback"
    assert finding.cause["segment"] == "5.4.0"


async def test_tc0224_model_unavailable_falls_back_with_one_call(
    server: MCPServer, catalog: EventCatalog
) -> None:
    intent = _intent(FUNNEL_DRAFT, catalog)

    finding, runner = await _run(
        server, intent, ScriptedLLM([], steps=[ProviderUnavailableError("down")])
    )

    assert finding.concluded_by == "fallback"
    assert "unavailable" in (finding.fallback_reason or "")
    assert [(c.tool, c.caller) for c in runner.log] == [("compare_segments", "fallback")]


async def test_tc0225_fallback_reuses_the_matching_comparison(
    server: MCPServer, catalog: EventCatalog
) -> None:
    intent = _intent(FUNNEL_DRAFT, catalog)
    llm = ScriptedLLM(
        [], steps=[[("compare_segments", compare_arguments(intent))], _finish("os", "iOS")]
    )

    _, runner = await _run(server, intent, llm)

    assert len(runner.log) == 1


async def test_tc0226_no_cause_is_accepted_when_the_evidence_has_none(
    server: MCPServer, catalog: EventCatalog
) -> None:
    intent = _intent(QUIET_DRAFT, catalog)
    llm = ScriptedLLM(
        [], steps=[[("compare_segments", compare_arguments(intent))], _finish(None, None)]
    )

    finding, _ = await _run(server, intent, llm)

    assert (finding.concluded_by, finding.cause) == ("agent", None)


async def test_tc0227_tool_errors_are_logged_and_returned_to_the_model(
    server: MCPServer, catalog: EventCatalog
) -> None:
    intent = _intent(FUNNEL_DRAFT, catalog)
    bad = ("count_events", {"event": "refunds", "start": "2026-09-01", "end": "2026-09-30"})
    llm = ScriptedLLM(
        [],
        steps=[
            [bad],
            [("compare_segments", compare_arguments(intent))],
            _finish("app_version", "5.4.0"),
        ],
    )

    finding, runner = await _run(server, intent, llm)

    assert runner.log[0].ok is False
    assert (runner.log[0].error or {}).get("code") == "not_tracked"
    tool_reply = llm.requests[1].messages[-1]
    assert tool_reply["role"] == "tool"
    assert "not_tracked" in tool_reply["content"]
    assert finding.concluded_by == "agent"
