"""Understand a question: the model fills a structured intent, code checks and resolves it.

The model maps the user's words to tracked events and dimensions by meaning,
using the catalogue's descriptions; nothing here matches keywords. Code then
holds the model to the catalogue: an event it invents is treated as not
tracked, a filter value is matched to the real values, and periods become
dates against the last day of data (see `periods.py`). One repair round
sends the problems back to the model; a second failure is an `IntentError`.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent.periods import PeriodSpec, Window, cohort_window, previous, resolve
from app.analytics.catalog import DIMENSIONS, PURCHASE_FUNNEL, Dimension
from app.analytics.models import ConversionMetric, CountMetric, EventCatalog, RetentionMetric
from app.llm.types import Completer, LLMRequest, ToolSpec

IntentKind = Literal["explain_change", "measure", "not_answerable"]
Metric = CountMetric | ConversionMetric | RetentionMetric


class MetricDraft(BaseModel):
    """The metric the question is about."""

    kind: Literal["count", "conversion", "retention"] = Field(
        description=(
            "count: how many times an event happened or how many users did it. conversion: share "
            "of users who went from the first step to the last. retention: share of a signup "
            "cohort who came back exactly N days later."
        )
    )
    event: str | None = Field(None, description="count: the tracked event name.")
    measure: Literal["events", "users"] = Field(
        "events", description="count: occurrences or unique users."
    )
    steps: list[str] = Field(
        default_factory=list, description="conversion: tracked event names in order."
    )
    day: int | None = Field(None, ge=1, le=30, description="retention: N in Day-N retention.")


class FilterDraft(BaseModel):
    """Restrict the question to some values of one dimension."""

    dimension: Dimension
    values: list[str] = Field(min_length=1)


class TermDraft(BaseModel):
    """Something the user mentioned that would be an event, and what it maps to."""

    said: str = Field(description="The user's words.")
    event: str | None = Field(
        description="The tracked event with that meaning, or null when none has it."
    )


class IntentDraft(BaseModel):
    """What the model returns through `submit_intent`."""

    kind: IntentKind = Field(
        description=(
            "explain_change: the user wants to know why a metric moved or what drove it. "
            "measure: the user wants a number, a trend or a breakdown. not_answerable: the "
            "question is not about this product's tracked data."
        )
    )
    metric: MetricDraft | None = None
    period: PeriodSpec = Field(
        description="The period asked about (the current period for a change)."
    )
    baseline: PeriodSpec | None = Field(
        None, description="What to compare with, only if the user names it."
    )
    filters: list[FilterDraft] = Field(default_factory=list)
    dimensions: list[Dimension] = Field(
        default_factory=list, description="Dimensions the user wants examined; empty means all."
    )
    group_by: Dimension | None = Field(
        None, description="measure: split the number by this dimension."
    )
    interval: Literal["total", "day", "week"] = Field(
        "total", description="measure: a total or a series."
    )
    terms: list[TermDraft] = Field(
        default_factory=list,
        description=(
            "Every product action the question mentions, each mapped to a tracked event or null."
        ),
    )


class Intent(BaseModel):
    """A question the tools can answer, with every assumption written down."""

    question: str
    kind: Literal["explain_change", "measure", "not_tracked", "not_answerable"]
    metric: Metric | None = None
    current: Window | None = None
    baseline: Window | None = None
    filters: dict[Dimension, list[str]] = Field(default_factory=dict)
    dimensions: list[Dimension] = Field(default_factory=lambda: list(DIMENSIONS))
    group_by: Dimension | None = None
    interval: Literal["total", "day", "week"] = "total"
    untracked: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class IntentError(Exception):
    """The question could not be turned into a valid intent."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Tool schemas must be self-contained: replace every $ref with its definition."""
    defs = schema.pop("$defs", {})

    def walk(node: object) -> object:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[str(node["$ref"]).rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    inlined = walk(schema)
    assert isinstance(inlined, dict)  # noqa: S101 - a dict walks to a dict
    return inlined


SUBMIT_INTENT = ToolSpec(
    name="submit_intent",
    description="Submit the structured intent of the user's question.",
    parameters=_inline_refs(IntentDraft.model_json_schema()),
)


def system_prompt(catalog: EventCatalog) -> str:
    """The catalogue and the rules, as the model sees them."""
    events = "\n".join(f"- {e.name}: {e.description}" for e in catalog.events)
    dims = "\n".join(
        f"- {d.name} ({d.description}): {', '.join(d.values)}" for d in catalog.dimensions
    )
    return (
        "You turn a product analytics question into a structured intent by calling submit_intent.\n"
        f"Data covers {catalog.dataset_start} to {catalog.dataset_end}; "
        f"treat {catalog.dataset_end} "
        "as today.\n\n"
        f"Tracked events:\n{events}\n\nDimensions and their values:\n{dims}\n\n"
        "Rules:\n"
        "- Map the user's words to events and values by meaning, whatever words they use. "
        "Use only the names and values listed above.\n"
        "- List every product action the user mentions in terms. If no tracked event has that "
        "meaning, set its event to null; never substitute a different event.\n"
        "- Conversion with only an end step named starts at the step just before it in the "
        f"purchase funnel ({' > '.join(PURCHASE_FUNNEL)}).\n"
        "- Retention without an event means signup to session_start; without N it means Day 7.\n"
        "- Leave baseline null unless the user names what to compare with.\n"
        "- Words naming a segment (a platform, a country, a channel, an app version) are filters."
    )


def _match_value(value: str, valid: list[str]) -> str | None:
    folded = {v.casefold(): v for v in valid}
    return folded.get(value.strip().casefold())


def _metric(draft: MetricDraft, known: set[str], problems: list[str]) -> Metric | None:
    def check(name: str | None, role: str) -> None:
        if name is None:
            problems.append(f"metric.{role} is missing")
        elif name not in known:
            problems.append(f"metric.{role} '{name}' is not a tracked event name")

    if draft.kind == "count":
        check(draft.event, "event")
        return CountMetric(event=draft.event or "", measure=draft.measure)
    if draft.kind == "conversion":
        if len(draft.steps) < 2:  # a conversion has a start and an end
            problems.append("metric.steps needs at least two events")
        for step in draft.steps:
            check(step, "steps")
        return ConversionMetric(steps=draft.steps or ["?", "?"])
    return RetentionMetric(day=draft.day or 7)


def resolve_intent(question: str, draft: IntentDraft, catalog: EventCatalog) -> Intent:
    """Hold the draft to the catalogue and turn its periods into dates."""
    known = {e.name for e in catalog.events}
    first, last = catalog.dataset_start, catalog.dataset_end
    untracked = [t.said for t in draft.terms if t.event is None or t.event not in known]
    if draft.kind == "not_answerable":
        return Intent(question=question, kind="not_answerable", untracked=untracked)
    if draft.metric is None:
        if untracked:
            return Intent(question=question, kind="not_tracked", untracked=untracked)
        raise IntentError(["metric is missing"])
    named = [draft.metric.event] if draft.metric.kind == "count" else draft.metric.steps
    if untracked and any(name is None or name not in known for name in named):
        return Intent(question=question, kind="not_tracked", untracked=untracked)

    problems: list[str] = []
    metric = _metric(draft.metric, known, problems)
    values = {d.name: d.values for d in catalog.dimensions}
    filters: dict[Dimension, list[str]] = {}
    for f in draft.filters:
        matched = [_match_value(v, values[f.dimension]) for v in f.values]
        bad = [v for v, m in zip(f.values, matched, strict=True) if m is None]
        if bad:
            problems.append(
                f"filter {f.dimension} has unknown values {bad}; valid: {values[f.dimension]}"
            )
        filters.setdefault(f.dimension, []).extend(m for m in matched if m)
    if problems:
        raise IntentError(problems)

    assumptions = [f"The data ends on {last}, which stands for today."]
    try:
        if isinstance(metric, RetentionMetric):
            current = cohort_window(draft.period, first, last, metric.day)
            assumptions.append(
                f"Day-{metric.day} retention is measured for users who signed up "
                f"{current.label()}, "
                f"the latest cohorts whose day {metric.day} is in the data."
            )
        else:
            default = 60 if draft.kind == "measure" else 7
            current = resolve(draft.period, first, last, default_days=default)
        baseline = None
        if draft.kind == "explain_change":
            if draft.baseline is not None:
                baseline = resolve(draft.baseline, first, last)
            else:
                baseline = previous(current, first)
                assumptions.append(
                    f"Compared with the {current.days} days before: {baseline.label()}."
                )
    except ValueError as exc:
        raise IntentError([str(exc)]) from exc
    return Intent(
        question=question,
        kind=draft.kind,
        metric=metric,
        current=current,
        baseline=baseline,
        filters=filters,
        dimensions=list(draft.dimensions) or list(DIMENSIONS),
        group_by=draft.group_by,
        interval=draft.interval,
        untracked=untracked,
        assumptions=assumptions,
    )


async def parse_intent(question: str, catalog: EventCatalog, llm: Completer) -> Intent:
    """Ask the model for the intent; send problems back once; then give up."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    problems: list[str] = []
    for _ in range(2):
        response = await llm.complete(
            LLMRequest(
                feature="intent_parse",
                system=system_prompt(catalog),
                messages=messages,
                tools=[SUBMIT_INTENT],
                tool_choice=SUBMIT_INTENT.name,
            )
        )
        call = next((c for c in response.tool_calls if c.name == SUBMIT_INTENT.name), None)
        if call is None:
            problems = ["submit_intent was not called"]
            messages = [
                *messages,
                response.message(),
                {"role": "user", "content": "Call submit_intent."},
            ]
            continue
        try:
            return resolve_intent(question, IntentDraft.model_validate(call.arguments), catalog)
        except ValidationError as exc:
            problems = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        except IntentError as exc:
            problems = exc.problems
        messages = [
            *messages,
            response.message(),
            {"role": "tool", "tool_call_id": call.id, "content": "Invalid: " + "; ".join(problems)},
        ]
    raise IntentError(problems)
