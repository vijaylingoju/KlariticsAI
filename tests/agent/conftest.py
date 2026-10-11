"""A scripted model: it answers each feature from a script, so every agent path runs offline.

It stands in for the model's judgement only. What the model would actually
say is tested on recorded responses in the eval suite (M3).
"""

from collections.abc import Sequence
from typing import Any

from app.agent.intent import IntentDraft, resolve_intent
from app.agent.investigate import compare_arguments
from app.analytics.service import AnalyticsService
from app.llm.routing import HAIKU
from app.llm.types import LLMRequest, LLMResponse, ToolCall, Usage

Step = list[tuple[str, dict[str, Any]]]


def response(text: str = "", calls: Step | None = None) -> LLMResponse:
    """A model response with these tool calls."""
    return LLMResponse(
        text=text,
        tool_calls=[
            ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls or [])
        ],
        stop_reason="tool_calls" if calls else "stop",
        model=HAIKU,
        usage=Usage(input_tokens=100, output_tokens=20),
        cost_usd=0.0002,
    )


class ScriptedLLM:
    """Plays a script per feature; an Exception in a script is raised instead."""

    def __init__(
        self,
        intents: Sequence[dict[str, Any] | Exception],
        steps: Sequence[Step | Exception] | None = None,
        narrative: str | Exception = "The change is concentrated in one segment.",
    ) -> None:
        self.intents = list(intents)
        self.steps = list(steps or [])
        self.narrative = narrative
        self.requests: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        if req.feature == "intent_parse":
            item: Any = self.intents.pop(0)
            if isinstance(item, Exception):
                raise item
            return response(calls=[("submit_intent", item)])
        if req.feature == "investigate":
            step: Any = (
                self.steps.pop(0)
                if self.steps
                else [("finish", {"dimension": None, "segment": None, "reasoning": "-"})]
            )
            if isinstance(step, Exception):
                raise step
            return response(calls=step)
        if isinstance(self.narrative, Exception):
            raise self.narrative
        return response(text=self.narrative)

    def count(self, feature: str) -> int:
        return sum(1 for r in self.requests if r.feature == feature)


FUNNEL_DRAFT: dict[str, Any] = {
    "kind": "explain_change",
    "metric": {"kind": "conversion", "steps": ["checkout_started", "purchase_completed"]},
    "period": {"kind": "last_week"},
    "terms": [{"said": "purchases", "event": "purchase_completed"}],
}
RETENTION_DRAFT: dict[str, Any] = {
    "kind": "explain_change",
    "metric": {"kind": "retention", "day": 7},
    "period": {"kind": "last_week"},
    "filters": [{"dimension": "os", "values": ["android"]}],
}
SIGNUP_DRAFT: dict[str, Any] = {
    "kind": "explain_change",
    "metric": {"kind": "count", "event": "signup"},
    "period": {"kind": "between", "start": "2026-08-26", "end": "2026-09-04"},
    "baseline": {"kind": "between", "start": "2026-08-16", "end": "2026-08-25"},
    "terms": [{"said": "signups", "event": "signup"}],
}
QUIET_DRAFT: dict[str, Any] = {
    "kind": "explain_change",
    "metric": {"kind": "conversion", "steps": ["checkout_started", "purchase_completed"]},
    "period": {"kind": "between", "start": "2026-09-01", "end": "2026-09-07"},
}

QUESTION = "Why did purchases drop last week?"


def funnel_steps(service: AnalyticsService) -> list[Step]:
    """The model compares the right periods and names 5.4.0."""
    intent = resolve_intent(
        QUESTION, IntentDraft.model_validate(FUNNEL_DRAFT), service.list_events()
    )
    return [
        [("compare_segments", compare_arguments(intent))],
        [("finish", {"dimension": "app_version", "segment": "5.4.0", "reasoning": "r"})],
    ]
