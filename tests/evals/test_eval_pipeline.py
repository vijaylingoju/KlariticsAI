"""The eval's own correctness: graders and the pipeline under a perfect model (US-07-001).

`oracle_llm` answers each case exactly as its label says, so these tests
prove the scenarios, the tools, the fallback rules and the graders agree with
the labels. What the real model understands is measured by the eval run on
recorded responses (`make eval`), not here.
"""

import asyncio
from typing import Any

import pytest
from evals.analyst import graders
from evals.analyst.run import check_gate, load_cases, summarise
from mcp.server.mcpserver import MCPServer

from app.agent.analyst import Analyst, Answer
from app.agent.intent import IntentDraft, resolve_intent
from app.agent.investigate import compare_arguments
from app.analytics.service import AnalyticsService
from tests.agent.conftest import ScriptedLLM

BASE = [c for c in load_cases(None) if c["variant"] == "base"]
# q08 leaves its periods to the reader; the oracle reads them as the campaign window.
OPEN_PERIODS = {
    "current": {"start": "2026-08-26", "end": "2026-09-04"},
    "baseline": {"start": "2026-08-16", "end": "2026-08-25"},
}


def _between(window: dict[str, str]) -> dict[str, str]:
    return {"kind": "between", **window}


def oracle_draft(case: dict[str, Any]) -> dict[str, Any]:
    """The intent a perfect reader would submit for this case."""
    exp = case["expected"]
    if exp["kind"] == "not_tracked":
        return {
            "kind": "explain_change",
            "metric": None,
            "period": {"kind": "last_week"},
            "terms": [{"said": exp["untracked_any"][0], "event": None}],
        }
    current = exp.get("current") or OPEN_PERIODS["current"]
    draft: dict[str, Any] = {
        "kind": exp["kind"],
        "metric": exp["metric"],
        "period": _between(current),
        "filters": [{"dimension": k, "values": v} for k, v in exp.get("filters", {}).items()],
    }
    if exp["kind"] == "explain_change":
        draft["baseline"] = _between(exp.get("baseline") or OPEN_PERIODS["baseline"])
    if exp.get("group_by"):
        draft["group_by"] = exp["group_by"]
    return draft


def oracle_llm(case: dict[str, Any], service: AnalyticsService) -> ScriptedLLM:
    """Intent, investigation and a numberless narrative, all as the label says."""
    draft = oracle_draft(case)
    exp = case["expected"]
    steps: list[Any] = []
    if exp["kind"] == "explain_change":
        intent = resolve_intent(
            case["input"]["question"], IntentDraft.model_validate(draft), service.list_events()
        )
        cause = exp["cause"] or {"dimension": None, "segment": None}
        steps = [
            [("compare_segments", compare_arguments(intent))],
            [("finish", {**cause, "reasoning": "label"})],
        ]
    return ScriptedLLM(
        [draft], steps=steps, narrative="The answer follows from the evidence above."
    )


async def _answer(server: MCPServer, case: dict[str, Any], service: AnalyticsService) -> Answer:
    return await Analyst(server, oracle_llm(case, service)).ask(case["input"]["question"])


@pytest.fixture(scope="module")
def oracle_rows(server: MCPServer, service: AnalyticsService) -> list[dict[str, Any]]:
    """Every base case answered once by the oracle; module-scoped, so in its own event loop."""
    rows = []
    for case in BASE:
        answer = asyncio.run(_answer(server, case, service))
        grades = {
            "root_cause": graders.root_cause(case, answer),
            "intent": graders.intent_match(case, answer),
            "numbers": graders.numbers(case, answer, graders.truth(case, service)),
            "budget": graders.within_budget(answer),
        }
        rows.append(
            {
                "id": case["id"],
                "group": case["group"],
                "variant": "base",
                "kind": answer.kind,
                "concluded_by": answer.concluded_by,
                "resolved": graders.resolved(answer),
                "tool_calls": len(answer.tool_calls),
                "removed_sentences": len(answer.removed_sentences),
                "llm": answer.llm.model_dump(),
                "latency_ms": 1,
                "scores": {k: g.score for k, g in grades.items()},
                "details": {k: g.detail for k, g in grades.items()},
            }
        )
    return rows


def test_tc0500_golden_set_has_15_questions_with_two_paraphrases_each() -> None:
    cases = load_cases(None)

    groups = {c["group"] for c in cases}
    assert (len(cases), len(groups), len(BASE)) == (45, 15, 15)
    assert all(sum(1 for c in cases if c["group"] == g) == 3 for g in groups)
    assert all(c["labelled_by"] and c["labelled_at"] for c in cases)


@pytest.mark.parametrize("case_id", [c["id"] for c in BASE])
def test_tc0501_a_perfect_reader_scores_every_case(
    oracle_rows: list[dict[str, Any]], case_id: str
) -> None:
    row = next(r for r in oracle_rows if r["id"] == case_id)

    assert row["scores"]["root_cause"] == 1.0, row["details"]["root_cause"]
    assert row["scores"]["intent"] in (1.0, None), row["details"]["intent"]
    assert row["scores"]["numbers"] in (1.0, None), row["details"]["numbers"]
    assert row["scores"]["budget"] == 1.0


def test_tc0502_a_perfect_reader_passes_the_gate_with_no_fallback(
    oracle_rows: list[dict[str, Any]],
) -> None:
    summary = summarise(oracle_rows)

    assert check_gate(summary) == []
    assert summary["fallback_rate"] == 0.0


def test_tc0503_a_null_answer_scores_zero_on_every_grader(service: AnalyticsService) -> None:
    null = Answer(question="q", kind="clarify", narrative="")

    for case in BASE:
        assert graders.root_cause(case, null).score == 0.0
        assert graders.intent_match(case, null).score in (0.0, None)
        assert graders.numbers(case, null, graders.truth(case, service)).score in (0.0, None)


def test_tc0504_gate_fails_on_errors_and_low_accuracy() -> None:
    summary = {
        "root_cause_accuracy": 0.5,
        "numeric_accuracy": 1.0,
        "intent_accuracy": 1.0,
        "max_tool_calls": 9,
        "errors": 2,
    }

    failures = check_gate(summary)

    assert failures == ["root_cause_accuracy: 0.5 < 0.87", "max_tool_calls: 9 > 8", "errors: 2 > 0"]
