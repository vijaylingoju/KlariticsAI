"""From evidence to words: the evidence pack, the model's narrative, and its check.

The narrator sees only a small evidence pack, each number with the text it
should be written as. The guardrail checks the narrative against that same
pack, so a number the model invents or misreads removes its sentence. When
nothing survives, or the model is unavailable, a template narrative built
from the pack answers instead: it can only state supported numbers.
"""

import json
from typing import Any

from pydantic import BaseModel, Field

from app.agent.intent import Intent
from app.agent.tools import ToolCallRecord
from app.analytics.models import ConversionMetric, CountMetric, RetentionMetric
from app.guardrails.numbers import Evidence, check_narrative, limit_words, word_count
from app.llm.types import Completer, LLMError, LLMRequest

MAX_WORDS = 120


class Narrative(BaseModel):
    """The words the user reads and how they were checked."""

    text: str
    source: str = Field(description="model or template")
    removed_sentences: list[str] = Field(default_factory=list)
    numbers_checked: int = 0


def metric_label(intent: Intent) -> str:
    """The metric in words."""
    m = intent.metric
    if isinstance(m, CountMetric):
        return f"{m.event} {'unique users' if m.measure == 'users' else 'events'}"
    if isinstance(m, ConversionMetric):
        return f"conversion from {m.steps[0]} to {m.steps[-1]}"
    if isinstance(m, RetentionMetric):
        return f"Day-{m.day} retention"
    return "the metric"


def sentence_case(text: str) -> str:
    """First letter upper, the rest as written (event names and codes keep their case)."""
    return text[:1].upper() + text[1:]


def is_rate(intent: Intent) -> bool:
    """Conversion and retention are rates; counts are not."""
    return not isinstance(intent.metric, CountMetric)


def fmt_value(value: float | None, rate: bool) -> str | None:
    """62.1% for a rate, 1,234 for a count."""
    if value is None:
        return None
    return f"{value * 100:.1f}%" if rate else f"{value:,.0f}"


def fmt_change(value: float | None, rate: bool) -> str | None:
    """9.8 points for a rate change, 1,234 for a count change; the sign goes in words."""
    if value is None:
        return None
    return f"{abs(value) * 100:.1f} points" if rate else f"{abs(value):,.0f}"


def _segment_view(seg: dict[str, Any], rate: bool) -> dict[str, Any]:
    view = {
        "dimension": seg["dimension"],
        "segment": seg["segment"],
        "baseline_value": seg.get("baseline_value"),
        "current_value": seg.get("current_value"),
        "contribution": seg.get("contribution"),
        "share_of_change": seg.get("share_of_change"),
        "explained": seg.get("explained"),
    }
    view["display"] = {
        "baseline_value": fmt_value(seg.get("baseline_value"), rate),
        "current_value": fmt_value(seg.get("current_value"), rate),
        "contribution": fmt_change(seg.get("contribution"), rate),
        "share_of_change": f"{abs(seg.get('share_of_change') or 0) * 100:.0f}%",
        "explained": f"{min(max(seg.get('explained') or 0, 0), 1) * 100:.0f}%",
    }
    return view


def _rest_rate(result: dict[str, Any], seg: dict[str, Any]) -> float | None:
    """The rate of everyone outside the segment in the current period."""
    current = result.get("current", {})
    num, den = current.get("numerator"), current.get("denominator")
    rate, size = seg.get("current_value"), seg.get("current_size")
    if not den or rate is None or not size or den - size <= 0:
        return None
    return round(float(num - rate * size) / float(den - size), 4)


def explain_pack(
    intent: Intent, record: ToolCallRecord | None, cause: dict[str, Any] | None
) -> dict[str, Any]:
    """The numbers an explanation may use."""
    rate = is_rate(intent)
    pack: dict[str, Any] = {
        "question": intent.question,
        "metric": metric_label(intent),
        "current_period": intent.current.label() if intent.current else None,
        "baseline_period": intent.baseline.label() if intent.baseline else None,
        "filters": intent.filters,
        "not_tracked": intent.untracked,
    }
    if record is None or record.result is None:
        return pack
    result = record.result
    base, cur = result["baseline"]["value"], result["current"]["value"]
    pack.update(
        baseline_value=base,
        current_value=cur,
        change=result["change"],
        relative_change=result.get("relative_change"),
        direction="down" if result["change"] < 0 else "up" if result["change"] > 0 else "flat",
    )
    pack["display"] = {
        "baseline_value": fmt_value(base, rate),
        "current_value": fmt_value(cur, rate),
        "change": fmt_change(result["change"], rate),
        "relative_change": None
        if result.get("relative_change") is None
        else f"{abs(result['relative_change']) * 100:.0f}%",
    }
    if cause is not None:
        view = _segment_view(cause, rate)
        if rate:
            rest = _rest_rate(result, cause)
            view["rest_current_value"] = rest
            view["display"]["rest_current_value"] = fmt_value(rest, rate)
        pack["cause"] = view
    else:
        pack["cause"] = None
    others = [s for s in result.get("top_contributors", []) if cause is None or s is not cause][:3]
    pack["other_contributors"] = [_segment_view(s, rate) for s in others if s != cause]
    return pack


def measure_pack(intent: Intent, record: ToolCallRecord | None) -> dict[str, Any]:
    """The numbers a measurement answer may use."""
    pack: dict[str, Any] = {
        "question": intent.question,
        "metric": metric_label(intent),
        "period": intent.current.label() if intent.current else None,
        "filters": intent.filters,
        "not_tracked": intent.untracked,
    }
    if record is None or record.result is None:
        return pack
    result = record.result
    if record.tool == "count_events":
        pack["total"] = result["total"]
        pack["display"] = {"total": f"{result['total']:,}"}
        if result.get("groups"):
            pack["groups"] = {g["segment"]: g["value"] for g in result["groups"]}
        if result.get("series"):
            values = [p["value"] for p in result["series"]]
            pack["series"] = {
                "first": values[0],
                "last": values[-1],
                "min": min(values),
                "max": max(values),
            }
    elif record.tool == "funnel":
        pack["steps"] = [
            {
                "event": s["event"],
                "users": s["users"],
                "conversion_from_previous": s["conversion_from_previous"],
            }
            for s in result["steps"]
        ]
        pack["overall_conversion"] = result["overall_conversion"]
        pack["display"] = {"overall_conversion": fmt_value(result["overall_conversion"], rate=True)}
        if result.get("groups"):
            pack["groups"] = {g["segment"]: g["conversion"] for g in result["groups"]}
    elif record.tool == "retention":
        pack["cohort_users"] = result["cohort_users"]
        pack["days"] = {f"day_{d['day']}": d["retention"] for d in result["days"]}
        pack["display"] = {
            f"day_{d['day']}": fmt_value(d["retention"], rate=True) for d in result["days"]
        }
        if result.get("groups"):
            pack["groups"] = {
                g["segment"]: {f"day_{d['day']}": d["retention"] for d in g["days"]}
                for g in result["groups"]
            }
    return pack


def evidence_of(pack: dict[str, Any]) -> Evidence:
    """What the guardrail accepts: every number in the pack and what derives from them."""
    numeric = {k: v for k, v in pack.items() if k not in ("question", "display")}
    return Evidence.from_results([numeric])


def template(intent: Intent, pack: dict[str, Any]) -> str:
    """A plain answer built only from the pack."""
    parts: list[str] = []
    display = pack.get("display", {})
    if intent.kind == "explain_change" and "current_value" in pack:
        verb = {"down": "fell", "up": "rose", "flat": "did not change"}[pack["direction"]]
        parts.append(
            f"{sentence_case(pack['metric'])} {verb} from {display['baseline_value']} "
            f"({pack['baseline_period']}) to {display['current_value']} ({pack['current_period']})."
        )
        cause = pack.get("cause")
        if cause:
            line = (
                f"The change comes from {cause['dimension']} {cause['segment']}: "
                f"it moved from {cause['display']['baseline_value']} "
                f"to {cause['display']['current_value']}"
            )
            if cause["display"].get("rest_current_value"):
                line += f", against {cause['display']['rest_current_value']} for everyone else"
            parts.append(
                line
                + f", and removing it takes away {cause['display']['explained']} of the change."
            )
        else:
            parts.append("No single segment explains the change; it is spread across segments.")
    elif "total" in pack:
        parts.append(f"{sentence_case(pack['metric'])} for {pack['period']}: {display['total']}.")
    elif "overall_conversion" in pack:
        parts.append(
            f"{sentence_case(pack['metric'])} for {pack['period']}: "
            f"{display['overall_conversion']}."
        )
    elif "days" in pack:
        days = ", ".join(f"{k.replace('_', ' ').capitalize()} {v}" for k, v in display.items())
        parts.append(f"Retention for users who signed up {pack['period']}: {days}.")
    if intent.untracked:
        parts.append(f"Not tracked: {', '.join(intent.untracked)}.")
    return " ".join(parts)


NARRATE_SYSTEM = (
    "You write the answer to a product analytics question for a product manager, from an evidence "
    "pack. At most 100 words, plain prose, no headings or lists. Use only numbers from the pack, "
    "written exactly as in its display fields. "
    "Say what changed, then which segment drove it and how "
    "strongly the evidence points there; if cause is null, say no single segment explains it. "
    "If not_tracked lists anything, say those events are not tracked. "
    "Do not speculate about reasons "
    "the data does not show."
)


async def narrate(intent: Intent, pack: dict[str, Any], llm: Completer) -> Narrative:
    """The model's narrative, checked; the template when nothing usable comes back."""

    evidence = evidence_of(pack)
    try:
        response = await llm.complete(
            LLMRequest(
                feature="narrate",
                system=NARRATE_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(pack, default=str, separators=(",", ":")),
                    }
                ],
            )
        )
    except LLMError:
        return _template_narrative(intent, pack, evidence)
    checked = check_narrative(response.text, evidence)
    text = limit_words(checked.text, MAX_WORDS)
    if not text or word_count(text) < 5:  # a fragment is not an answer
        fallback = _template_narrative(intent, pack, evidence)
        return fallback.model_copy(update={"removed_sentences": checked.removed})
    return Narrative(
        text=text,
        source="model",
        removed_sentences=checked.removed,
        numbers_checked=checked.numbers_checked,
    )


def _template_narrative(intent: Intent, pack: dict[str, Any], evidence: Evidence) -> Narrative:
    checked = check_narrative(template(intent, pack), evidence)
    return Narrative(
        text=limit_words(checked.text, MAX_WORDS),
        source="template",
        removed_sentences=checked.removed,
        numbers_checked=checked.numbers_checked,
    )
