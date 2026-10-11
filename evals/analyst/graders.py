"""Deterministic graders for the analyst eval. No model judges anything here.

Each grader is `(case, answer, truth) -> Grade` with a score in [0, 1] or
None when it does not apply to the case. Expected answers come from the
planted ground truth (`ground_truth.json`), not from the model.
"""

from dataclasses import dataclass, field
from typing import Any

from app.agent.analyst import Answer
from app.agent.investigate import on_intent
from app.agent.tools import MAX_TOOL_CALLS
from app.analytics.models import (
    CompareQuery,
    CountQuery,
    DateRange,
    FunnelQuery,
    RetentionQuery,
)
from app.analytics.service import AnalyticsService

TOLERANCE = 1e-4


@dataclass
class Grade:
    """A score in [0, 1], or None when the grader does not apply, with why."""

    score: float | None
    detail: dict[str, Any] = field(default_factory=dict)


def _metric_key(metric: dict[str, Any] | None) -> tuple[object, ...] | None:
    if not metric:
        return None
    kind = metric.get("kind")
    if kind == "conversion":
        return ("conversion", tuple(metric.get("steps", [])))
    if kind == "retention":
        return ("retention", metric.get("day", 7))
    return ("count", metric.get("event"))


def _window(value: dict[str, Any] | None) -> tuple[str, str] | None:
    return None if value is None else (str(value["start"]), str(value["end"]))


def resolved(answer: Answer) -> dict[str, Any] | None:
    """What the analyst understood, in the eval's terms."""
    if answer.intent is None:
        return None
    intent = answer.intent.model_dump(mode="json")
    return {
        "kind": intent["kind"],
        "metric": _metric_key(intent.get("metric")),
        "current": _window(intent.get("current")),
        "baseline": _window(intent.get("baseline")),
        "filters": {k: sorted(v) for k, v in (intent.get("filters") or {}).items()},
        "group_by": intent.get("group_by"),
    }


def root_cause(case: dict[str, Any], answer: Answer) -> Grade:
    """The right conclusion: the planted cause, no cause, not tracked, or the right measurement."""
    exp = case["expected"]
    if exp["kind"] == "not_tracked":
        said = " ".join(answer.intent.untracked if answer.intent else []).lower()
        ok = answer.kind == "not_tracked" and any(term in said for term in exp["untracked_any"])
        return Grade(1.0 if ok else 0.0, {"kind": answer.kind, "untracked": said})
    if exp["kind"] == "measure":
        tools = [c.tool for c in answer.tool_calls]
        group_by = answer.tool_calls[0].arguments.get("group_by") if answer.tool_calls else None
        ok = answer.kind == "measure" and tools == [exp["tool"]] and group_by == exp.get("group_by")
        return Grade(
            1.0 if ok else 0.0, {"kind": answer.kind, "tools": tools, "group_by": group_by}
        )
    got = (
        None
        if answer.cause is None
        else {"dimension": answer.cause.dimension, "segment": answer.cause.segment}
    )
    ok = answer.kind == "explain_change" and got == exp["cause"]
    return Grade(1.0 if ok else 0.0, {"kind": answer.kind, "cause": got, "expected": exp["cause"]})


def intent_match(case: dict[str, Any], answer: Answer) -> Grade:
    """The metric, periods and filters the question means; open periods are not checked."""
    exp = case["expected"]
    if exp["kind"] == "not_tracked":
        return Grade(None)
    got = resolved(answer)
    if got is None:
        return Grade(0.0, {"resolved": None})
    checks = {
        "kind": got["kind"] == exp["kind"],
        "metric": got["metric"] == _metric_key(exp["metric"]),
        "filters": got["filters"] == {k: sorted(v) for k, v in exp.get("filters", {}).items()},
    }
    if exp.get("current"):
        checks["current"] = got["current"] == _window(exp["current"])
    if exp.get("baseline"):
        checks["baseline"] = got["baseline"] == _window(exp["baseline"])
    return Grade(sum(checks.values()) / len(checks), {"checks": checks, "resolved": got})


def truth(case: dict[str, Any], service: AnalyticsService) -> dict[str, float] | None:
    """The headline numbers for the expected question, computed directly from the store."""
    exp = case["expected"]
    if not exp.get("check_numbers"):
        return None
    current = DateRange.model_validate(exp["current"])
    filters = exp.get("filters", {})
    metric = exp["metric"]
    if exp["kind"] == "explain_change":
        result = service.compare_segments(
            CompareQuery.model_validate(
                {
                    "metric": metric,
                    "current": current,
                    "baseline": exp["baseline"],
                    "filters": filters,
                }
            )
        )
        return {"baseline": result.baseline.value, "current": result.current.value}
    if metric["kind"] == "count":
        count = service.count_events(
            CountQuery(event=metric["event"], start=current.start, end=current.end, filters=filters)
        )
        return {"total": float(count.total)}
    if metric["kind"] == "conversion":
        funnel = service.funnel(
            FunnelQuery(
                steps=metric["steps"],
                start=current.start,
                end=current.end,
                filters=filters,
                group_by=exp.get("group_by"),
            )
        )
        out = {"overall": funnel.overall_conversion}
        out.update({f"group:{g.segment}": g.conversion for g in funnel.groups})
        return out
    retention = service.retention(
        RetentionQuery(
            cohort_start=current.start,
            cohort_end=current.end,
            days=[metric["day"]],
            filters=filters,
        )
    )
    return {"retention": retention.days[0].retention}


def _answer_numbers(answer: Answer) -> dict[str, float]:
    if answer.kind == "explain_change" and answer.intent is not None:
        record = next((r for r in reversed(answer.tool_calls) if on_intent(r, answer.intent)), None)
        if record is None or record.result is None:
            return {}
        return {
            "baseline": record.result["baseline"]["value"],
            "current": record.result["current"]["value"],
        }
    record = answer.tool_calls[0] if answer.tool_calls else None
    if record is None or record.result is None:
        return {}
    result = record.result
    if record.tool == "count_events":
        return {"total": float(result["total"])}
    if record.tool == "funnel":
        out = {"overall": result["overall_conversion"]}
        out.update({f"group:{g['segment']}": g["conversion"] for g in result.get("groups", [])})
        return out
    return {"retention": result["days"][0]["retention"]}


def numbers(case: dict[str, Any], answer: Answer, expected: dict[str, float] | None) -> Grade:
    """Share of headline numbers the answer got right; None where periods are left open."""
    if expected is None:
        return Grade(None)
    got = _answer_numbers(answer)
    hits = {k: k in got and abs(got[k] - v) <= TOLERANCE for k, v in expected.items()}
    return Grade(sum(hits.values()) / len(hits), {"expected": expected, "got": got})


def within_budget(answer: Answer) -> Grade:
    """At most eight tool calls."""
    return Grade(
        1.0 if len(answer.tool_calls) <= MAX_TOOL_CALLS else 0.0,
        {"tool_calls": len(answer.tool_calls)},
    )
