"""Vega-Lite chart specs, built from tool results only.

Charts carry their data inline, so a saved report renders the same numbers
it was answered with, with no query at view time.
"""

from typing import Any

from app.agent.intent import Intent
from app.agent.narrative import is_rate, metric_label, sentence_case
from app.agent.tools import ToolCallRecord

SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"


def _bar(
    title: str, rows: list[dict[str, Any]], x: str, y: str, y_title: str, fmt: str
) -> dict[str, Any]:
    return {
        "$schema": SCHEMA,
        "title": title,
        "data": {"values": rows},
        "mark": "bar",
        "encoding": {
            "x": {"field": x, "type": "nominal", "sort": "-y", "title": None},
            "y": {"field": y, "type": "quantitative", "title": y_title, "axis": {"format": fmt}},
            "tooltip": [{"field": x}, {"field": y, "format": fmt}],
        },
    }


def _explain_charts(
    intent: Intent, result: dict[str, Any], cause: dict[str, Any] | None
) -> list[dict[str, Any]]:
    rate = is_rate(intent)
    fmt = ".1%" if rate else ",.0f"
    dimension = cause["dimension"] if cause else None
    segments: list[dict[str, Any]] = []
    for breakdown in result.get("breakdowns", []):
        if breakdown["dimension"] == dimension:
            segments = breakdown["segments"]
    if not segments:
        segments = result.get("top_contributors", [])
        dimension = "top segments"
    contribution = [
        {
            "segment": f"{s['dimension']}={s['segment']}"
            if dimension == "top segments"
            else s["segment"],
            "contribution": s["contribution"],
        }
        for s in segments
    ]
    charts = [
        _bar(
            f"Contribution to the change in {metric_label(intent)}, by {dimension}",
            contribution,
            "segment",
            "contribution",
            "Points of change" if rate else "Change in count",
            ".1%" if rate else ",.0f",
        )
    ]
    if dimension != "top segments":
        periods = [
            {"segment": s["segment"], "period": period, "value": s[key]}
            for s in segments
            for period, key in (("baseline", "baseline_value"), ("current", "current_value"))
            if s.get(key) is not None
        ]
        charts.append(
            {
                "$schema": SCHEMA,
                "title": (
                    f"{sentence_case(metric_label(intent))} by {dimension}, baseline and current"
                ),
                "data": {"values": periods},
                "mark": "bar",
                "encoding": {
                    "x": {"field": "segment", "type": "nominal", "title": None},
                    "xOffset": {"field": "period"},
                    "y": {
                        "field": "value",
                        "type": "quantitative",
                        "title": None,
                        "axis": {"format": fmt},
                    },
                    "color": {
                        "field": "period",
                        "type": "nominal",
                        "sort": ["baseline", "current"],
                    },
                    "tooltip": [
                        {"field": "segment"},
                        {"field": "period"},
                        {"field": "value", "format": fmt},
                    ],
                },
            }
        )
    return charts


def _measure_charts(
    intent: Intent, record: ToolCallRecord, result: dict[str, Any]
) -> list[dict[str, Any]]:
    label = metric_label(intent)
    if record.tool == "count_events":
        if result.get("series"):
            return [
                {
                    "$schema": SCHEMA,
                    "title": sentence_case(label),
                    "data": {"values": result["series"]},
                    "mark": {"type": "line", "point": True},
                    "encoding": {
                        "x": {"field": "period", "type": "temporal", "title": None},
                        "y": {"field": "value", "type": "quantitative", "title": None},
                    },
                }
            ]
        if result.get("groups"):
            return [
                _bar(
                    f"{sentence_case(label)} by {intent.group_by}",
                    result["groups"],
                    "segment",
                    "value",
                    "",
                    ",.0f",
                )
            ]
        return []
    if record.tool == "funnel":
        steps = [
            {"step": f"{i + 1}. {s['event']}", "users": s["users"]}
            for i, s in enumerate(result["steps"])
        ]
        chart = _bar(sentence_case(label), steps, "step", "users", "Users", ",.0f")
        chart["encoding"]["x"]["sort"] = None
        return [chart]
    if record.tool == "retention":
        days = [{"day": f"Day {d['day']}", "retention": d["retention"]} for d in result["days"]]
        return [_bar(sentence_case(label), days, "day", "retention", "Retained", ".1%")]
    return []


def charts_for(
    intent: Intent, record: ToolCallRecord | None, cause: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """The charts for an answer; none when its evidence call failed."""
    if record is None or not record.ok or record.result is None:
        return []
    if record.tool == "compare_segments":
        return _explain_charts(intent, record.result, cause)
    return _measure_charts(intent, record, record.result)
