"""Investigate a change: the model drills with the tools, code checks its conclusion.

The model gets the resolved intent, the MCP tools and a budget of seven
calls, keeping one in reserve for the fallback so the whole question never
exceeds eight. It ends by calling `finish` with the segment it blames, or
none. Its conclusion is accepted only when evidence it gathered backs it:

- a compare_segments call for exactly the intent (metric, periods, filters)
  exists, so it drilled into the dimensions before naming anything;
- a named cause is marked `likely_cause` in that evidence;
- no cause named means that evidence has no likely cause.

Otherwise, or when the model fails or runs out of calls, the deterministic
plan answers: one compare_segments call across all dimensions (or the
matching one already made), and its top likely cause.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel

from app.agent.intent import Intent, _inline_refs
from app.agent.narrative import metric_label
from app.agent.tools import BudgetSpentError, ToolCallRecord, ToolRunner, compact
from app.llm.types import Completer, LLMError, LLMRequest, ToolSpec

AGENT_CALLS = 7

FINISH = ToolSpec(
    name="finish",
    description=(
        "End the investigation with the segment that caused the change, or null if none does."
    ),
    parameters={
        "type": "object",
        "properties": {
            "dimension": {
                "type": ["string", "null"],
                "description": "Dimension of the cause, or null.",
            },
            "segment": {
                "type": ["string", "null"],
                "description": "Segment value of the cause, or null.",
            },
            "reasoning": {"type": "string", "description": "One sentence: why this segment."},
        },
        "required": ["dimension", "segment", "reasoning"],
    },
)


class Finding(BaseModel):
    """The investigation's conclusion and how it was reached."""

    cause: dict[str, Any] | None
    evidence_call: int | None
    concluded_by: Literal["agent", "fallback"]
    fallback_reason: str | None = None
    agent_reasoning: str | None = None


def compare_arguments(intent: Intent) -> dict[str, Any]:
    """compare_segments arguments for exactly this intent."""
    # Explain intents always carry a metric and both windows (resolve_intent).
    assert intent.metric is not None  # noqa: S101
    assert intent.current is not None  # noqa: S101
    assert intent.baseline is not None  # noqa: S101
    args: dict[str, Any] = {
        "metric": intent.metric.model_dump(mode="json"),
        "current": intent.current.model_dump(mode="json"),
        "baseline": intent.baseline.model_dump(mode="json"),
        "dimensions": list(intent.dimensions),
        "top_n": 5,
    }
    if intent.filters:
        args["filters"] = {k: list(v) for k, v in intent.filters.items()}
    return args


def _same_metric(a: object, b: dict[str, Any]) -> bool:
    if not isinstance(a, dict):
        return False
    keys = set(a) | set(b)
    return all(a.get(k, b.get(k)) == b.get(k, a.get(k)) for k in keys)


def on_intent(record: ToolCallRecord, intent: Intent) -> bool:
    """A successful compare_segments call for the intent's metric, periods and filters."""
    if record.tool != "compare_segments" or not record.ok:
        return False
    want = compare_arguments(intent)
    args = record.arguments
    return (
        _same_metric(args.get("metric"), want["metric"])
        and args.get("current") == want["current"]
        and args.get("baseline") == want["baseline"]
        and {k: sorted(v) for k, v in (args.get("filters") or {}).items()}
        == {k: sorted(v) for k, v in want.get("filters", {}).items()}
    )


def likely_causes(record: ToolCallRecord) -> list[dict[str, Any]]:
    """Segments the evidence marks as likely causes, best first."""
    return [s for s in (record.result or {}).get("top_contributors", []) if s.get("likely_cause")]


def validate(
    intent: Intent, log: list[ToolCallRecord], dimension: str | None, segment: str | None
) -> tuple[dict[str, Any] | None, int | None, str | None]:
    """The backed cause and its call, or the reason the conclusion is rejected."""
    matching = [r for r in log if on_intent(r, intent)]
    if not matching:
        return None, None, "no comparison across dimensions for the question"
    record = matching[-1]
    causes = likely_causes(record)
    if dimension is None or segment is None:
        if causes:
            return None, None, "named no cause although the evidence marks one"
        return None, record.index, None
    for cause in causes:
        if cause["dimension"] == dimension and str(cause["segment"]) == str(segment):
            return cause, record.index, None
    return (
        None,
        None,
        f"named {dimension}={segment}, which the evidence does not mark as a likely cause",
    )


def system_prompt(intent: Intent, budget: int) -> str:
    """The task, the budget and the first call, as the model sees them."""
    return (
        "You investigate why a product metric changed, using analytics tools, then call finish.\n"
        f"Question: {intent.question}\n"
        f"Metric: {metric_label(intent)}. "
        f"Current period: {intent.current.label() if intent.current else '-'}. "
        f"Baseline: {intent.baseline.label() if intent.baseline else '-'}. "
        f"Filters: {intent.filters or 'none'}.\n"
        f"You have {budget} tool calls. "
        "Start with compare_segments using exactly these arguments:\n"
        f"{json.dumps(compare_arguments(intent))}\n"
        "A segment is a cause only if compare_segments marks it likely_cause. "
        "You may spend further "
        "calls to confirm it, for example the same comparison filtered to the cause, or the metric "
        "split by the cause's dimension. Then call finish with that segment, or with nulls when no "
        "segment is marked likely_cause."
    )


def _tool_specs(tools: list[Any]) -> list[ToolSpec]:
    return [
        ToolSpec(
            name=t.name,
            description=t.description or "",
            parameters=_inline_refs(dict(t.input_schema)),
        )
        for t in tools
    ]


async def run_agent(intent: Intent, runner: ToolRunner, llm: Completer) -> Finding | str:
    """The model's investigation; a Finding when it concludes, else why it did not."""
    listed = await runner.client.list_tools()
    tools = [*_tool_specs(listed.tools), FINISH]
    budget = min(AGENT_CALLS, runner.remaining - 1)
    messages: list[dict[str, Any]] = [{"role": "user", "content": intent.question}]
    used = 0
    for _ in range(budget + 2):
        response = await llm.complete(
            LLMRequest(
                feature="investigate",
                system=system_prompt(intent, budget),
                messages=messages,
                tools=tools,
            )
        )
        messages.append(response.message())
        if not response.tool_calls:
            return "the model stopped without calling finish"
        replies: list[dict[str, Any]] = []
        for call in response.tool_calls:
            if call.name == FINISH.name:
                dim, seg = call.arguments.get("dimension"), call.arguments.get("segment")
                cause, evidence, problem = validate(intent, runner.log, dim, seg)
                if problem:
                    return problem
                return Finding(
                    cause=cause,
                    evidence_call=evidence,
                    concluded_by="agent",
                    agent_reasoning=str(call.arguments.get("reasoning", ""))[:300],
                )
            if used >= budget:
                return f"the tool budget of {budget} calls ran out"
            record = await runner.call(call.name, call.arguments, caller="agent")
            used += 1
            replies.append({"role": "tool", "tool_call_id": call.id, "content": compact(record)})
        messages.extend(replies)
    return "the model did not finish"


async def fallback(intent: Intent, runner: ToolRunner, reason: str) -> Finding:
    """The deterministic plan: the matching comparison, made once, and its best likely cause."""
    matching = [r for r in runner.log if on_intent(r, intent)]
    record = (
        matching[-1]
        if matching
        else await runner.call("compare_segments", compare_arguments(intent), "fallback")
    )
    causes = likely_causes(record) if record.ok else []
    return Finding(
        cause=causes[0] if causes else None,
        evidence_call=record.index if record.ok else None,
        concluded_by="fallback",
        fallback_reason=reason,
    )


async def investigate(intent: Intent, runner: ToolRunner, llm: Completer) -> Finding:
    """The agent's backed conclusion, or the deterministic plan's."""
    try:
        outcome = await run_agent(intent, runner, llm)
    except LLMError as exc:
        outcome = f"the model was unavailable ({exc.code})"
    except BudgetSpentError:
        outcome = "the tool budget ran out"
    if isinstance(outcome, Finding):
        return outcome
    return await fallback(intent, runner, outcome)
