"""`Analyst.ask`: one question in, one evidence-backed answer out.

intent (model, checked) -> tools (agent loop or one planned call, at most
eight) -> narrative (model, number-checked, template fallback) -> charts,
contribution table and the full tool log.

The analyst reaches data only through the MCP server, in-process or over
HTTP, the same way any other MCP host would.
"""

from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from app.agent.charts import charts_for
from app.agent.intent import Intent, IntentError, parse_intent
from app.agent.investigate import Finding, investigate
from app.agent.narrative import Narrative, explain_pack, measure_pack, narrate
from app.agent.tools import ToolCallRecord, ToolRunner
from app.analytics.models import ConversionMetric, CountMetric, EventCatalog, RetentionMetric
from app.llm.types import Completer, LLMError, LLMRequest, LLMResponse
from mcp import Client

log = structlog.get_logger()

AnswerKind = Literal[
    "explain_change", "measure", "not_tracked", "not_answerable", "clarify", "unavailable"
]


class LLMUsage(BaseModel):
    """What the model calls for one answer cost."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class ContributionRow(BaseModel):
    """One segment's part in the change."""

    dimension: str
    segment: str
    baseline_value: float | None
    current_value: float | None
    change: float | None
    contribution: float
    share_of_change: float
    explained: float
    separation_z: float
    likely_cause: bool


class Answer(BaseModel):
    """Everything the user sees and everything needed to check it."""

    id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    question: str
    kind: AnswerKind
    narrative: str
    narrative_source: str = "template"
    removed_sentences: list[str] = Field(default_factory=list)
    numbers_checked: int = 0
    intent: Intent | None = None
    cause: ContributionRow | None = None
    concluded_by: Literal["agent", "fallback", "plan", "none"] = "none"
    fallback_reason: str | None = None
    charts: list[dict[str, Any]] = Field(default_factory=list)
    contribution_table: list[ContributionRow] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    llm: LLMUsage = Field(default_factory=LLMUsage)


class Meter:
    """Counts what one answer's model calls cost."""

    def __init__(self, llm: Completer) -> None:
        self.llm = llm
        self.usage = LLMUsage()

    async def complete(self, req: LLMRequest) -> LLMResponse:
        """Pass through and add up tokens and cost."""
        response = await self.llm.complete(req)
        self.usage.calls += 1
        self.usage.input_tokens += response.usage.input_tokens
        self.usage.output_tokens += response.usage.output_tokens
        self.usage.cost_usd = round(self.usage.cost_usd + response.cost_usd, 6)
        return response


def _row(seg: dict[str, Any]) -> ContributionRow:
    return ContributionRow.model_validate({k: seg.get(k) for k in ContributionRow.model_fields})


def contribution_table(
    record: ToolCallRecord | None, cause: dict[str, Any] | None
) -> list[ContributionRow]:
    """The cause's dimension in full, or the top contributors when there is no cause."""
    if record is None or record.result is None:
        return []
    if cause is not None:
        for breakdown in record.result.get("breakdowns", []):
            if breakdown["dimension"] == cause["dimension"]:
                return [_row(s) for s in breakdown["segments"]]
    return [_row(s) for s in record.result.get("top_contributors", [])]


def plan_call(intent: Intent) -> tuple[str, dict[str, Any]]:
    """The one tool call that answers a measurement question."""
    assert intent.current is not None  # noqa: S101 - measure intents have a period
    filters = {k: list(v) for k, v in intent.filters.items()}
    window = {"start": intent.current.start.isoformat(), "end": intent.current.end.isoformat()}
    m = intent.metric
    if isinstance(m, CountMetric):
        args: dict[str, Any] = {
            "event": m.event,
            "measure": m.measure,
            **window,
            "filters": filters,
        }
        if intent.group_by:
            args["group_by"] = intent.group_by
        else:
            args["interval"] = intent.interval
        return "count_events", args
    if isinstance(m, ConversionMetric):
        args = {"steps": m.steps, "window_hours": m.window_hours, **window, "filters": filters}
        return "funnel", args | ({"group_by": intent.group_by} if intent.group_by else {})
    assert isinstance(m, RetentionMetric)  # noqa: S101 - the metric union has three members
    args = {
        "cohort_start": window["start"],
        "cohort_end": window["end"],
        "days": [m.day],
        "start_event": m.start_event,
        "return_event": m.return_event,
        "filters": filters,
    }
    return "retention", args | ({"group_by": intent.group_by} if intent.group_by else {})


def _no_data_answer(
    question: str, kind: AnswerKind, text: str, intent: Intent | None, usage: LLMUsage
) -> Answer:
    return Answer(question=question, kind=kind, narrative=text, intent=intent, llm=usage)


class Analyst:
    """Answers questions over one MCP analytics server."""

    def __init__(self, target: MCPServer | str, llm: Completer) -> None:
        self.target = target
        self.llm = llm
        self._catalog: EventCatalog | None = None

    async def catalog(self, client: Client) -> EventCatalog:
        """The tracked events and dimensions, fetched once."""
        if self._catalog is None:
            result = await client.call_tool("list_events", {})
            self._catalog = EventCatalog.model_validate(result.structured_content)
        return self._catalog

    async def ask(self, question: str) -> Answer:
        """Answer one question."""
        meter = Meter(self.llm)
        async with Client(self.target) as client:
            catalog = await self.catalog(client)
            tracked = ", ".join(e.name for e in catalog.events)
            try:
                intent = await parse_intent(question, catalog, meter)
            except IntentError as exc:
                log.info("intent rejected", problems=exc.problems)
                text = (
                    "I could not turn that into a question about the tracked data. "
                    f"Tracked events: {tracked}."
                )
                return _no_data_answer(question, "clarify", text, None, meter.usage)
            except LLMError as exc:
                log.warning("intent unavailable", code=exc.code)
                text = (
                    "The analyst cannot reach the language model right now, so no analysis was run."
                )
                return _no_data_answer(question, "unavailable", text, None, meter.usage)
            if intent.kind == "not_tracked":
                text = (
                    f"{', '.join(intent.untracked)} "
                    f"{'is' if len(intent.untracked) == 1 else 'are'} not tracked, "
                    f"so there is no data to answer with. Tracked events: {tracked}."
                )
                return _no_data_answer(question, "not_tracked", text, intent, meter.usage)
            if intent.kind == "not_answerable":
                text = (
                    "That is not a question the product's event data can answer. "
                    f"Tracked events: {tracked}."
                )
                return _no_data_answer(question, "not_answerable", text, intent, meter.usage)
            runner = ToolRunner(client)
            if intent.kind == "explain_change":
                return await self._explain(intent, runner, meter)
            return await self._measure(intent, runner, meter)

    async def _explain(self, intent: Intent, runner: ToolRunner, meter: Meter) -> Answer:
        finding: Finding = await investigate(intent, runner, meter)
        record = runner.log[finding.evidence_call - 1] if finding.evidence_call else None
        pack = explain_pack(intent, record, finding.cause)
        narrative: Narrative = await narrate(intent, pack, meter)
        table = contribution_table(record, finding.cause)
        log.info(
            "answered",
            kind="explain_change",
            concluded_by=finding.concluded_by,
            fallback_reason=finding.fallback_reason,
            tool_calls=len(runner.log),
            cost_usd=meter.usage.cost_usd,
        )
        return Answer(
            question=intent.question,
            kind="explain_change",
            narrative=narrative.text,
            narrative_source=narrative.source,
            removed_sentences=narrative.removed_sentences,
            numbers_checked=narrative.numbers_checked,
            intent=intent,
            cause=_row(finding.cause) if finding.cause else None,
            concluded_by=finding.concluded_by,
            fallback_reason=finding.fallback_reason,
            charts=charts_for(intent, record, finding.cause),
            contribution_table=table,
            tool_calls=runner.log,
            llm=meter.usage,
        )

    async def _measure(self, intent: Intent, runner: ToolRunner, meter: Meter) -> Answer:
        tool, args = plan_call(intent)
        record = await runner.call(tool, args, caller="plan")
        pack = measure_pack(intent, record if record.ok else None)
        narrative = await narrate(intent, pack, meter)
        log.info("answered", kind="measure", tool=tool, ok=record.ok, cost_usd=meter.usage.cost_usd)
        return Answer(
            question=intent.question,
            kind="measure",
            narrative=narrative.text,
            narrative_source=narrative.source,
            removed_sentences=narrative.removed_sentences,
            numbers_checked=narrative.numbers_checked,
            intent=intent,
            concluded_by="plan",
            charts=charts_for(intent, record, None),
            tool_calls=runner.log,
            llm=meter.usage,
        )
