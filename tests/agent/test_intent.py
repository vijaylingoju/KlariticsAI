"""The model's intent is held to the catalogue before anything runs (US-04-001, US-05-002)."""

import json
from datetime import date
from typing import Any

import pytest

from app.agent.intent import (
    SUBMIT_INTENT,
    IntentDraft,
    IntentError,
    parse_intent,
    resolve_intent,
    system_prompt,
)
from app.analytics.models import ConversionMetric, CountMetric, EventCatalog, RetentionMetric
from app.analytics.service import AnalyticsService
from app.llm.types import ProviderUnavailableError
from tests.agent.conftest import FUNNEL_DRAFT, RETENTION_DRAFT, SIGNUP_DRAFT, ScriptedLLM


@pytest.fixture(scope="module")
def catalog(service: AnalyticsService) -> EventCatalog:
    return service.list_events()


def _resolve(draft: dict[str, Any], catalog: EventCatalog, question: str = "q") -> Any:
    return resolve_intent(question, IntentDraft.model_validate(draft), catalog)


def test_tc0210_explain_draft_resolves_to_dates_and_a_metric(catalog: EventCatalog) -> None:
    intent = _resolve(FUNNEL_DRAFT, catalog)

    assert intent.kind == "explain_change"
    assert intent.metric == ConversionMetric(steps=["checkout_started", "purchase_completed"])
    assert (intent.current.start, intent.current.end) == (date(2026, 9, 24), date(2026, 9, 30))
    assert (intent.baseline.start, intent.baseline.end) == (date(2026, 9, 17), date(2026, 9, 23))
    assert any("2026-09-30" in a for a in intent.assumptions)


def test_tc0211_retention_last_week_uses_observable_cohorts_and_fixes_filter_case(
    catalog: EventCatalog,
) -> None:
    intent = _resolve(RETENTION_DRAFT, catalog)

    assert intent.metric == RetentionMetric(day=7)
    assert intent.filters == {"os": ["Android"]}
    assert (intent.current.start, intent.current.end) == (date(2026, 9, 17), date(2026, 9, 23))
    assert (intent.baseline.start, intent.baseline.end) == (date(2026, 9, 10), date(2026, 9, 16))


def test_tc0212_named_baseline_is_kept(catalog: EventCatalog) -> None:
    intent = _resolve(SIGNUP_DRAFT, catalog)

    assert intent.metric == CountMetric(event="signup")
    assert (intent.baseline.start, intent.baseline.end) == (date(2026, 8, 16), date(2026, 8, 25))


def test_tc0213_untracked_term_makes_the_question_not_tracked(catalog: EventCatalog) -> None:
    draft = {
        "kind": "explain_change",
        "metric": {"kind": "count", "event": None},
        "period": {"kind": "last_week"},
        "terms": [{"said": "refunds", "event": None}],
    }

    intent = _resolve(draft, catalog)

    assert (intent.kind, intent.untracked, intent.metric) == ("not_tracked", ["refunds"], None)


def test_tc0213_event_the_model_invents_is_not_tracked(catalog: EventCatalog) -> None:
    draft = {
        "kind": "measure",
        "metric": {"kind": "count", "event": "refund_issued"},
        "period": {"kind": "last_week"},
        "terms": [{"said": "refunds", "event": "refund_issued"}],
    }

    intent = _resolve(draft, catalog)

    assert (intent.kind, intent.untracked) == ("not_tracked", ["refunds"])


def test_tc0214_unknown_event_without_a_term_is_a_problem(catalog: EventCatalog) -> None:
    draft = {
        "kind": "measure",
        "metric": {"kind": "count", "event": "orders"},
        "period": {"kind": "all"},
    }

    with pytest.raises(IntentError) as caught:
        _resolve(draft, catalog)

    assert "metric.event 'orders' is not a tracked event name" in caught.value.problems


def test_tc0214_unknown_filter_value_lists_the_valid_ones(catalog: EventCatalog) -> None:
    draft = {**FUNNEL_DRAFT, "filters": [{"dimension": "country", "values": ["Brazil"]}]}

    with pytest.raises(IntentError, match=r"unknown values \['Brazil'\].*BR"):
        _resolve(draft, catalog)


def test_tc0215_mixed_question_answers_the_tracked_part_and_lists_the_rest(
    catalog: EventCatalog,
) -> None:
    draft = {**FUNNEL_DRAFT, "terms": [*FUNNEL_DRAFT["terms"], {"said": "refunds", "event": None}]}

    intent = _resolve(draft, catalog)

    assert (intent.kind, intent.untracked) == ("explain_change", ["refunds"])


def test_tc0216_submit_intent_schema_is_self_contained() -> None:
    text = json.dumps(SUBMIT_INTENT.parameters)

    assert "$ref" not in text
    assert "$defs" not in text


def test_tc0216_prompt_lists_every_event_and_dimension_value(catalog: EventCatalog) -> None:
    prompt = system_prompt(catalog)

    assert all(e.name in prompt for e in catalog.events)
    assert all(v in prompt for d in catalog.dimensions for v in d.values)
    assert "2026-09-30" in prompt


async def test_tc0217_one_invalid_draft_is_repaired(catalog: EventCatalog) -> None:
    bad = {
        "kind": "measure",
        "metric": {"kind": "count", "event": "orders"},
        "period": {"kind": "all"},
    }
    llm = ScriptedLLM([bad, FUNNEL_DRAFT])

    intent = await parse_intent("q", catalog, llm)

    assert intent.kind == "explain_change"
    repair = llm.requests[1].messages[-1]
    assert repair["role"] == "tool"
    assert "orders" in repair["content"]


async def test_tc0217_two_invalid_drafts_give_up(catalog: EventCatalog) -> None:
    bad = {
        "kind": "measure",
        "metric": {"kind": "count", "event": "orders"},
        "period": {"kind": "all"},
    }
    llm = ScriptedLLM([bad, bad])

    with pytest.raises(IntentError):
        await parse_intent("q", catalog, llm)

    assert llm.count("intent_parse") == 2


async def test_tc0217_model_failure_is_raised_to_the_caller(catalog: EventCatalog) -> None:
    with pytest.raises(ProviderUnavailableError):
        await parse_intent("q", catalog, ScriptedLLM([ProviderUnavailableError("down")]))
