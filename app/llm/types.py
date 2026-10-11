"""Requests, responses and errors of the LLM gateway.

Messages and tools use the OpenAI-compatible chat format that OpenRouter
speaks, so a provider passes them through unchanged.
"""

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

Feature = Literal["intent_parse", "investigate", "narrate"]


class ToolSpec(BaseModel):
    """A function the model may call."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    parameters: dict[str, Any]


class LLMRequest(BaseModel):
    """One model call. `feature` picks the route: model, token cap and timeout."""

    model_config = ConfigDict(frozen=True)

    feature: Feature
    system: str
    messages: list[dict[str, Any]]
    tools: list[ToolSpec] = Field(default_factory=list)
    # A tool name forces that call (structured output); "auto" lets the model choose.
    tool_choice: str = "auto"
    max_tokens: int | None = None


class ToolCall(BaseModel):
    """A function call the model asked for, arguments already parsed."""

    id: str
    name: str
    arguments: dict[str, Any]


class Usage(BaseModel):
    """Tokens the provider billed for one call."""

    input_tokens: int
    output_tokens: int


class LLMResponse(BaseModel):
    """What came back, with what it cost. `model` is the provider's, not the request's."""

    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: str
    model: str
    usage: Usage
    cost_usd: float
    latency_ms: int = 0
    replayed: bool = False

    def message(self) -> dict[str, Any]:
        """This response as an assistant message to append to the conversation."""
        out: dict[str, Any] = {"role": "assistant", "content": self.text or None}
        if self.tool_calls:
            out["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": _dumps(c.arguments)},
                }
                for c in self.tool_calls
            ]
        return out


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class LLMError(Exception):
    """Base for gateway failures; `code` is stable and machine-readable."""

    code = "llm_error"
    retryable = False

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class BudgetExceededError(LLMError):
    """The call's worst-case cost would take total spend past the limit. Nothing was sent."""

    code = "budget_exceeded"


class FeatureDisabledError(LLMError):
    """The route is switched off (LLM_KILL_<FEATURE>=1). Nothing was sent."""

    code = "feature_disabled"


class ProviderUnavailableError(LLMError):
    """The provider failed in a way a retry might fix: timeout, 429, 5xx, no key."""

    code = "provider_unavailable"
    retryable = True


class ProviderRejectedError(LLMError):
    """The provider refused the request itself (4xx other than 429). Never retried."""

    code = "provider_rejected"


class ReplayMissingError(LLMError):
    """Replay mode found no recording for this request. Record it with LLM_MODE=record."""

    code = "replay_missing"


class Completer(Protocol):
    """Anything that completes a model request: the gateway, or a meter around it."""

    async def complete(self, req: LLMRequest) -> LLMResponse:
        """One model call."""
        ...
