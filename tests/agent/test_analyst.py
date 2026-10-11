"""One question to one answer, end to end over the MCP server (US-04, US-05, US-06-001)."""

import re

import pytest
from mcp.server.mcpserver import MCPServer

from app.agent.analyst import Analyst
from app.analytics.service import AnalyticsService
from app.llm.types import ProviderUnavailableError
from tests.agent.conftest import FUNNEL_DRAFT, QUESTION, RETENTION_DRAFT, ScriptedLLM, funnel_steps


async def test_tc0230_explain_answer_has_narrative_charts_table_and_log(
    server: MCPServer, service: AnalyticsService
) -> None:
    llm = ScriptedLLM(
        [FUNNEL_DRAFT],
        steps=funnel_steps(service),
        narrative="Purchases fell on app version 5.4.0.",
    )

    answer = await Analyst(server, llm).ask(QUESTION)

    assert (answer.kind, answer.concluded_by) == ("explain_change", "agent")
    assert answer.cause is not None
    assert (answer.cause.dimension, answer.cause.segment) == ("app_version", "5.4.0")
    assert answer.narrative == "Purchases fell on app version 5.4.0."
    assert len(answer.charts) == 2
    assert all(
        c["$schema"].startswith("https://vega.github.io/schema/vega-lite/") for c in answer.charts
    )
    assert {r.dimension for r in answer.contribution_table} == {"app_version"}
    assert [(c.tool, c.caller) for c in answer.tool_calls] == [("compare_segments", "agent")]
    assert answer.llm.calls == 4
    assert answer.llm.cost_usd > 0


async def test_tc0231_unsupported_number_is_removed_from_the_narrative(
    server: MCPServer, service: AnalyticsService
) -> None:
    text = "Purchases fell on app version 5.4.0. That cost 987,654 orders."
    llm = ScriptedLLM([FUNNEL_DRAFT], steps=funnel_steps(service), narrative=text)

    answer = await Analyst(server, llm).ask(QUESTION)

    assert answer.narrative == "Purchases fell on app version 5.4.0."
    assert answer.removed_sentences == ["That cost 987,654 orders."]


async def test_tc0232_narrative_is_capped_at_120_words(
    server: MCPServer, service: AnalyticsService
) -> None:
    long_text = " ".join(["Purchases fell on the newest app version across every market."] * 20)
    llm = ScriptedLLM([FUNNEL_DRAFT], steps=funnel_steps(service), narrative=long_text)

    answer = await Analyst(server, llm).ask(QUESTION)

    assert 0 < len(answer.narrative.split()) <= 120


async def test_tc0233_template_answers_when_the_narrator_is_unavailable(
    server: MCPServer, service: AnalyticsService
) -> None:
    llm = ScriptedLLM(
        [FUNNEL_DRAFT], steps=funnel_steps(service), narrative=ProviderUnavailableError("down")
    )

    answer = await Analyst(server, llm).ask(QUESTION)

    assert answer.narrative_source == "template"
    assert answer.removed_sentences == []
    assert "5.4.0" in answer.narrative
    assert re.search(r"\d+\.\d%", answer.narrative)


async def test_tc0234_untracked_event_answers_not_tracked_with_no_numbers(
    server: MCPServer,
) -> None:
    draft = {
        "kind": "explain_change",
        "metric": {"kind": "count", "event": None},
        "period": {"kind": "last_week"},
        "terms": [{"said": "refunds", "event": None}],
    }

    answer = await Analyst(server, ScriptedLLM([draft])).ask("Why did refunds go up last week?")

    assert answer.kind == "not_tracked"
    assert "refunds is not tracked" in answer.narrative
    assert not re.search(r"\d", answer.narrative)
    assert answer.tool_calls == []


async def test_tc0235_measure_question_makes_one_planned_call(server: MCPServer) -> None:
    draft = {
        "kind": "measure",
        "metric": {"kind": "count", "event": "signup", "measure": "users"},
        "period": {"kind": "last_week"},
        "interval": "day",
    }

    answer = await Analyst(server, ScriptedLLM([draft], narrative="Signups held steady.")).ask(
        "Daily signups last week?"
    )

    assert answer.kind == "measure"
    assert [(c.tool, c.caller) for c in answer.tool_calls] == [("count_events", "plan")]
    assert answer.tool_calls[0].arguments["interval"] == "day"
    assert answer.charts[0]["mark"]["type"] == "line"


async def test_tc0236_android_retention_question_falls_back_to_the_cause(server: MCPServer) -> None:
    answer = await Analyst(server, ScriptedLLM([RETENTION_DRAFT])).ask(
        "Why did Day-7 retention drop for Android users last week?"
    )

    assert answer.concluded_by == "fallback"
    assert answer.cause is not None
    assert (answer.cause.dimension, answer.cause.segment) == ("country", "BR")
    assert answer.tool_calls[-1].arguments["filters"] == {"os": ["Android"]}


async def test_tc0237_unparseable_question_asks_to_rephrase(server: MCPServer) -> None:
    bad = {
        "kind": "measure",
        "metric": {"kind": "count", "event": "orders"},
        "period": {"kind": "all"},
    }

    answer = await Analyst(server, ScriptedLLM([bad, bad])).ask("orders?")

    assert answer.kind == "clarify"
    assert "purchase_completed" in answer.narrative
    assert answer.tool_calls == []


async def test_tc0238_model_down_runs_no_analysis(server: MCPServer) -> None:
    answer = await Analyst(server, ScriptedLLM([ProviderUnavailableError("down")])).ask(QUESTION)

    assert answer.kind == "unavailable"
    assert answer.tool_calls == []


@pytest.mark.parametrize(
    ("metric", "extra", "tool", "mark"),
    [
        (
            {
                "kind": "conversion",
                "steps": ["product_viewed", "add_to_cart", "purchase_completed"],
            },
            {},
            "funnel",
            "bar",
        ),
        ({"kind": "retention", "day": 7}, {}, "retention", "bar"),
        (
            {"kind": "count", "event": "purchase_completed"},
            {"group_by": "country"},
            "count_events",
            "bar",
        ),
    ],
    ids=["funnel", "retention", "count_by_country"],
)
async def test_tc0239_measure_answers_chart_and_template_numbers_hold(
    server: MCPServer, metric: dict[str, object], extra: dict[str, object], tool: str, mark: str
) -> None:
    draft = {"kind": "measure", "metric": metric, "period": {"kind": "last_week"}, **extra}
    llm = ScriptedLLM([draft], narrative=ProviderUnavailableError("down"))

    answer = await Analyst(server, llm).ask("How are we doing?")

    assert [c.tool for c in answer.tool_calls] == [tool]
    assert answer.charts[0]["mark"] == mark
    assert answer.narrative_source == "template"
    assert answer.removed_sentences == []
    assert re.search(r"\d", answer.narrative)
