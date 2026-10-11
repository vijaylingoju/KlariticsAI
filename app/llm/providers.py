"""Where a request actually goes: OpenRouter, a recording of it, or both.

- `OpenRouterProvider` calls the OpenAI-compatible chat API.
- `ReplayProvider` serves a recorded response by request hash and never
  touches the network; CI and tests run on it.
- `RecordingProvider` calls a live provider and saves what it returns, so
  the next replay run has it.

A recording is keyed by a hash of everything that shapes the answer (model,
system, messages, tools, tool choice, token cap), so a changed prompt is a
missing recording, never a stale answer.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from app.llm.routing import Route
from app.llm.types import (
    LLMRequest,
    ProviderRejectedError,
    ProviderUnavailableError,
    ReplayMissingError,
    ToolCall,
    Usage,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class ProviderResult(BaseModel):
    """A provider's answer before the gateway prices and records it."""

    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    model: str
    usage: Usage
    # OpenRouter reports the billed cost; None means price it from usage.
    cost_usd: float | None = None
    replayed: bool = False


class Provider(Protocol):
    """Sends one request to a model."""

    async def complete(self, req: LLMRequest, route: Route) -> ProviderResult:
        """The model's answer, or a typed provider error."""
        ...


def wire_body(req: LLMRequest, route: Route) -> dict[str, Any]:
    """The chat-completions body for this request."""
    body: dict[str, Any] = {
        "model": route.model,
        "max_tokens": min(req.max_tokens or route.max_tokens, route.max_tokens),
        "messages": [{"role": "system", "content": req.system}, *req.messages],
    }
    if req.tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in req.tools
        ]
        body["tool_choice"] = (
            "auto"
            if req.tool_choice == "auto"
            else {"type": "function", "function": {"name": req.tool_choice}}
        )
    return body


def request_key(req: LLMRequest, route: Route) -> str:
    """Stable hash of everything that shapes the answer."""
    canonical = json.dumps(wire_body(req, route), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def _parse_arguments(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {"__invalid_json__": str(raw)}
    return parsed if isinstance(parsed, dict) else {"__invalid_json__": str(raw)}


def parse_completion(payload: dict[str, Any]) -> ProviderResult:
    """Read an OpenAI-compatible completion into a provider result."""
    choices = payload.get("choices") or []
    if not choices:
        raise ProviderUnavailableError("provider returned no choices", error=payload.get("error"))
    choice = choices[0]
    message = choice.get("message") or {}
    calls = [
        ToolCall(
            id=str(c.get("id") or f"call_{i}"),
            name=str((c.get("function") or {}).get("name", "")),
            arguments=_parse_arguments((c.get("function") or {}).get("arguments")),
        )
        for i, c in enumerate(message.get("tool_calls") or [])
    ]
    usage = payload.get("usage") or {}
    cost = usage.get("cost")
    return ProviderResult(
        text=str(message.get("content") or ""),
        tool_calls=calls,
        stop_reason=str(choice.get("finish_reason") or "unknown"),
        model=str(payload.get("model") or ""),
        usage=Usage(
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        ),
        cost_usd=float(cost) if cost is not None else None,
    )


class OpenRouterProvider:
    """OpenRouter's chat-completions API. The key is read once, never logged."""

    def __init__(self, api_key: str | None, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client

    async def complete(self, req: LLMRequest, route: Route) -> ProviderResult:
        """POST the request; map transport and status failures to typed errors."""
        if not self._api_key:
            raise ProviderUnavailableError("OPENROUTER_API_KEY is not set")
        body = wire_body(req, route)
        body["usage"] = {"include": True}
        headers = {"Authorization": f"Bearer {self._api_key}", "X-Title": "Klaritics AI Analyst"}
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.post(
                OPENROUTER_URL, json=body, headers=headers, timeout=route.timeout_s
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("provider timed out", timeout_s=route.timeout_s) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailableError(
                "provider unreachable", error=type(exc).__name__
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderUnavailableError("provider busy", status=response.status_code)
        if response.status_code >= 400:
            raise ProviderRejectedError(
                "provider rejected the request", status=response.status_code
            )
        return parse_completion(response.json())


class ReplayProvider:
    """Serves recorded responses; a missing one is an error naming its hash."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, req: LLMRequest, route: Route) -> Path:
        """Where this request's recording lives."""
        return self.directory / req.feature / f"{request_key(req, route)}.json"

    async def complete(self, req: LLMRequest, route: Route) -> ProviderResult:
        """The recorded answer, marked as replayed."""
        path = self.path_for(req, route)
        if not path.is_file():
            raise ReplayMissingError(
                "no recording for this request", feature=req.feature, key=path.stem, path=str(path)
            )
        recorded = json.loads(path.read_text())
        result = ProviderResult.model_validate(recorded["response"])
        return result.model_copy(update={"replayed": True})


class RecordingProvider:
    """Calls a live provider and saves each answer for replay."""

    def __init__(self, live: Provider, replay: ReplayProvider) -> None:
        self.live = live
        self.replay = replay

    async def complete(self, req: LLMRequest, route: Route) -> ProviderResult:
        """The live answer, written next to the request that produced it."""
        result = await self.live.complete(req, route)
        path = self.replay.path_for(req, route)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "request": wire_body(req, route),
            "response": result.model_dump(mode="json"),
        }
        path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
        return result
