"""The LLM gateway: caps, pricing, ledger, budget, replay, retries (US-03-001..003).

No test touches the network: providers are fakes, replays, or OpenRouter
over an in-memory httpx transport.
Test ids trace to docs/testing/test-cases.md.
"""

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog

from app.llm.gateway import MAX_RETRY_WAIT_S, Gateway, build_provider, worst_case_cost
from app.llm.ledger import Ledger
from app.llm.providers import (
    OPENROUTER_URL,
    OpenRouterProvider,
    ProviderResult,
    RecordingProvider,
    ReplayProvider,
    chat_url,
    request_key,
    wire_body,
)
from app.llm.routing import HAIKU, MAX_OUTPUT_TOKENS, ROUTES, Route, configure_model
from app.llm.types import (
    BudgetExceededError,
    FeatureDisabledError,
    LLMRequest,
    ProviderRejectedError,
    ProviderUnavailableError,
    ReplayMissingError,
    ToolSpec,
    Usage,
)

ROOT = Path(__file__).resolve().parents[2]
REQ = LLMRequest(
    feature="narrate",
    system="You write short answers.",
    messages=[{"role": "user", "content": "Say hi to customer@example.com"}],
)


def _result(**overrides: Any) -> ProviderResult:
    base: dict[str, Any] = {
        "text": "hi",
        "tool_calls": [],
        "stop_reason": "stop",
        "model": HAIKU,
        "usage": Usage(input_tokens=1000, output_tokens=200),
    }
    return ProviderResult(**(base | overrides))


class FakeProvider:
    """Answers from a script: each item is a result or an exception to raise."""

    def __init__(self, *script: ProviderResult | Exception) -> None:
        self.script = list(script)
        self.calls = 0

    async def complete(self, req: LLMRequest, route: Route) -> ProviderResult:
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def _no_sleep(_: float) -> None:
    return None


def _gateway(provider: Any, tmp_path: Path, limit: float = 8.0, **kwargs: Any) -> Gateway:
    return Gateway(provider, Ledger(tmp_path / "ledger.jsonl", limit), sleep=_no_sleep, **kwargs)


def test_tc0100_every_route_uses_haiku_and_caps_output_at_600() -> None:
    bodies = [
        wire_body(REQ.model_copy(update={"feature": f, "max_tokens": 5000}), r)
        for f, r in ROUTES.items()
    ]

    assert {b["model"] for b in bodies} == {"anthropic/claude-haiku-4.5"}
    assert max(b["max_tokens"] for b in bodies) <= MAX_OUTPUT_TOKENS == 600


async def test_tc0101_cost_is_priced_from_usage_when_the_provider_omits_it(tmp_path: Path) -> None:
    gateway = _gateway(FakeProvider(_result()), tmp_path)

    response = await gateway.complete(REQ)

    # 1,000 input at $1/M plus 200 output at $5/M.
    assert response.cost_usd == pytest.approx(0.002)
    assert (response.usage.input_tokens, response.usage.output_tokens) == (1000, 200)


async def test_tc0101_provider_reported_cost_wins(tmp_path: Path) -> None:
    gateway = _gateway(FakeProvider(_result(cost_usd=0.0031)), tmp_path)

    response = await gateway.complete(REQ)

    assert response.cost_usd == pytest.approx(0.0031)


async def test_tc0102_ledger_persists_spend_across_restarts(tmp_path: Path) -> None:
    gateway = _gateway(FakeProvider(_result(), _result()), tmp_path)
    await gateway.complete(REQ)
    await gateway.complete(REQ)

    reopened = Ledger(tmp_path / "ledger.jsonl", 8.0)

    assert reopened.calls == 2
    assert reopened.spent_usd == pytest.approx(0.004)
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert set(rows[0]) >= {"feature", "model", "input_tokens", "output_tokens", "cost_usd"}


async def test_tc0102_replayed_calls_do_not_count_against_the_limit(tmp_path: Path) -> None:
    gateway = _gateway(FakeProvider(_result(replayed=True, cost_usd=0.5)), tmp_path)

    await gateway.complete(REQ)

    assert Ledger(tmp_path / "ledger.jsonl", 8.0).spent_usd == 0.0


async def test_tc0103_call_over_budget_is_refused_before_sending(tmp_path: Path) -> None:
    provider = FakeProvider(_result())
    gateway = _gateway(provider, tmp_path, limit=0.0001)

    with pytest.raises(BudgetExceededError) as caught:
        await gateway.complete(REQ)

    assert provider.calls == 0
    assert caught.value.details["limit_usd"] == 0.0001


def test_tc0103_worst_case_assumes_every_output_token() -> None:
    route = ROUTES["narrate"]

    cost = worst_case_cost(REQ, route)

    assert cost >= route.max_tokens * 5 / 1_000_000


async def test_tc0104_replay_serves_the_recording_by_request_hash(tmp_path: Path) -> None:
    replay = ReplayProvider(tmp_path / "rec")
    recorder = RecordingProvider(FakeProvider(_result(text="recorded")), replay)
    await _gateway(recorder, tmp_path).complete(REQ)

    response = await _gateway(build_provider("replay", None, replay), tmp_path).complete(REQ)

    assert (response.text, response.replayed) == ("recorded", True)
    saved = json.loads(replay.path_for(REQ, ROUTES["narrate"]).read_text())
    assert saved["request"]["model"] == HAIKU


async def test_tc0104_missing_recording_fails_with_its_hash(tmp_path: Path) -> None:
    gateway = _gateway(ReplayProvider(tmp_path / "rec"), tmp_path)

    with pytest.raises(ReplayMissingError) as caught:
        await gateway.complete(REQ)

    assert caught.value.details["key"] == request_key(REQ, ROUTES["narrate"])


def test_tc0104_a_changed_prompt_is_a_different_recording() -> None:
    changed = REQ.model_copy(update={"system": "You write long answers."})

    assert request_key(REQ, ROUTES["narrate"]) != request_key(changed, ROUTES["narrate"])


async def test_tc0105_transient_failure_is_retried_once(tmp_path: Path) -> None:
    provider = FakeProvider(ProviderUnavailableError("busy"), _result(text="ok"))

    response = await _gateway(provider, tmp_path).complete(REQ)

    assert (response.text, provider.calls) == ("ok", 2)


async def test_tc0105_second_transient_failure_is_raised(tmp_path: Path) -> None:
    provider = FakeProvider(ProviderUnavailableError("busy"), ProviderUnavailableError("busy"))

    with pytest.raises(ProviderUnavailableError):
        await _gateway(provider, tmp_path).complete(REQ)

    assert provider.calls == 2


async def test_tc0105_rejected_request_is_never_retried(tmp_path: Path) -> None:
    provider = FakeProvider(ProviderRejectedError("bad request"))

    with pytest.raises(ProviderRejectedError):
        await _gateway(provider, tmp_path).complete(REQ)

    assert provider.calls == 1


async def test_tc0106_disabled_feature_is_refused_before_sending(tmp_path: Path) -> None:
    provider = FakeProvider(_result())

    with pytest.raises(FeatureDisabledError):
        await _gateway(provider, tmp_path, disabled=frozenset({"narrate"})).complete(REQ)

    assert provider.calls == 0


def _openrouter(handler: Any) -> OpenRouterProvider:
    return OpenRouterProvider(
        "test-key", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def test_tc0107_openrouter_sends_capped_request_and_parses_tool_calls() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "model": HAIKU,
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {"name": "submit", "arguments": '{"a": 1}'},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.00004},
            },
        )

    req = REQ.model_copy(
        update={
            "tools": [ToolSpec(name="submit", description="d", parameters={"type": "object"})],
            "tool_choice": "submit",
        }
    )
    result = await _openrouter(handler).complete(req, ROUTES["narrate"])

    assert seen["max_tokens"] == ROUTES["narrate"].max_tokens
    assert seen["tool_choice"] == {"type": "function", "function": {"name": "submit"}}
    assert seen["auth"] == "Bearer test-key"
    assert seen["usage"] == {"include": True}
    assert [(c.name, c.arguments) for c in result.tool_calls] == [("submit", {"a": 1})]
    assert result.cost_usd == pytest.approx(0.00004)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (429, ProviderUnavailableError),
        (503, ProviderUnavailableError),
        (400, ProviderRejectedError),
    ],
)
async def test_tc0107_openrouter_status_maps_to_a_typed_error(
    status: int, error: type[Exception]
) -> None:
    provider = _openrouter(lambda _: httpx.Response(status, json={"error": {"message": "x"}}))

    with pytest.raises(error):
        await provider.complete(REQ, ROUTES["narrate"])


async def test_tc0107_rejection_carries_the_provider_reason() -> None:
    # KAI-5: Groq 4xx answers were logged as a bare provider_rejected.
    body = {"error": {"code": "invalid_request_error", "message": "Unknown field"}}
    provider = _openrouter(lambda _: httpx.Response(400, json=body))

    with pytest.raises(ProviderRejectedError) as raised:
        await provider.complete(REQ, ROUTES["narrate"])

    assert raised.value.details == {
        "status": 400,
        "reason": "invalid_request_error",
        "detail": "Unknown field",
    }


async def test_tc0107_rejection_without_a_json_body_keeps_the_status() -> None:
    provider = _openrouter(lambda _: httpx.Response(404, text="not found"))

    with pytest.raises(ProviderRejectedError) as raised:
        await provider.complete(REQ, ROUTES["narrate"])

    assert raised.value.details == {"status": 404, "reason": None, "detail": None}


async def test_tc0109_rejected_call_is_logged_with_its_reason(tmp_path: Path) -> None:
    error = ProviderRejectedError("rejected", status=400, reason="tool_use_failed")
    gateway = _gateway(FakeProvider(error), tmp_path)

    with structlog.testing.capture_logs() as logs, pytest.raises(ProviderRejectedError):
        await gateway.complete(REQ)

    assert logs[-1]["event"] == "llm rejected"
    assert logs[-1]["reason"] == "tool_use_failed"


async def test_tc0107_rate_limit_carries_the_wait_the_provider_asks_for() -> None:
    # KAI-5: Groq's per-minute limit needs a wait of seconds, not the default half second.
    provider = _openrouter(lambda _: httpx.Response(429, headers={"retry-after": "7"}))

    with pytest.raises(ProviderUnavailableError) as raised:
        await provider.complete(REQ, ROUTES["narrate"])

    assert raised.value.details == {"status": 429, "retry_after_s": 7.0}


async def test_tc0107_invalid_tool_call_from_the_model_is_retryable() -> None:
    # KAI-5: Groq answers 400 tool_use_failed when the model writes a bad tool call.
    body = {"error": {"code": "tool_use_failed", "message": "Failed to call a function"}}
    provider = _openrouter(lambda _: httpx.Response(400, json=body))

    with pytest.raises(ProviderUnavailableError):
        await provider.complete(REQ, ROUTES["narrate"])


async def test_tc0105_retry_waits_as_long_as_the_provider_asks(tmp_path: Path) -> None:
    waits: list[float] = []

    async def record_sleep(seconds: float) -> None:
        waits.append(seconds)

    provider = FakeProvider(ProviderUnavailableError("busy", retry_after_s=7.0), _result())
    gateway = Gateway(provider, Ledger(tmp_path / "ledger.jsonl", 8.0), sleep=record_sleep)

    await gateway.complete(REQ)

    assert waits == [7.0]


async def test_tc0105_provider_wait_is_capped(tmp_path: Path) -> None:
    waits: list[float] = []

    async def record_sleep(seconds: float) -> None:
        waits.append(seconds)

    provider = FakeProvider(ProviderUnavailableError("busy", retry_after_s=3600.0), _result())
    gateway = Gateway(provider, Ledger(tmp_path / "ledger.jsonl", 8.0), sleep=record_sleep)

    await gateway.complete(REQ)

    assert waits == [MAX_RETRY_WAIT_S]


async def test_tc0107_openrouter_without_a_key_is_unavailable() -> None:
    with pytest.raises(ProviderUnavailableError):
        await OpenRouterProvider(None).complete(REQ, ROUTES["narrate"])


def test_tc0108_no_model_call_outside_the_gateway() -> None:
    pattern = re.compile(r"openrouter\.ai|chat/completions|import anthropic|from openai")
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "app").rglob("*.py")
        if path.parent.name != "llm" and pattern.search(path.read_text())
    ]

    assert offenders == []


async def test_tc0109_log_line_carries_cost_but_no_prompt_or_answer(tmp_path: Path) -> None:
    gateway = _gateway(FakeProvider(_result(text="secret answer")), tmp_path)

    with structlog.testing.capture_logs() as logs:
        await gateway.complete(REQ)

    line = next(entry for entry in logs if entry["event"] == "llm call")
    assert {"cost_usd", "input_tokens", "output_tokens", "model"} <= set(line)
    assert "customer@example.com" not in json.dumps(logs, default=str)
    assert "secret answer" not in json.dumps(logs, default=str)


def test_tc0110_no_model_setting_keeps_haiku_on_every_route() -> None:
    routes, prices = configure_model(None)

    assert routes == ROUTES
    assert {r.model for r in routes.values()} == {HAIKU}
    assert HAIKU in prices


def test_tc0110_model_setting_moves_every_route_and_keeps_the_caps() -> None:
    routes, prices = configure_model("qwen2.5:7b", 0, 0)

    assert {r.model for r in routes.values()} == {"qwen2.5:7b"}
    assert {f: r.max_tokens for f, r in routes.items()} == {
        f: r.max_tokens for f, r in ROUTES.items()
    }
    assert prices["qwen2.5:7b"].cost(1_000_000, 1_000_000) == 0


def test_tc0110_timeout_setting_applies_to_every_route() -> None:
    routes, _ = configure_model("qwen2.5:7b", 0, 0, timeout_s=180)
    default_routes, _ = configure_model(None)

    assert {r.timeout_s for r in routes.values()} == {180}
    assert default_routes == ROUTES


def test_tc0110_unpriced_model_is_refused() -> None:
    with pytest.raises(ValueError, match="LLM_PRICE_INPUT_PER_M"):
        configure_model("some/paid-model")


async def test_tc0110_gateway_prices_calls_with_the_configured_model(tmp_path: Path) -> None:
    routes, prices = configure_model("qwen2.5:7b", 0, 0)
    result = _result(model="qwen2.5:7b")
    gateway = _gateway(FakeProvider(result), tmp_path, routes=routes, prices=prices)

    response = await gateway.complete(REQ)

    assert response.model == "qwen2.5:7b"
    assert response.cost_usd == 0


def test_tc0110_chat_url_defaults_to_openrouter() -> None:
    assert chat_url(None) == OPENROUTER_URL
    assert chat_url("http://localhost:11434/v1/") == "http://localhost:11434/v1/chat/completions"


async def test_tc0110_local_server_is_called_without_a_key() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:7b",
                "choices": [{"finish_reason": "stop", "message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    url = chat_url("http://localhost:11434/v1")
    provider = OpenRouterProvider(
        None, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), url=url
    )
    result = await provider.complete(REQ, ROUTES["narrate"])

    assert seen == {"url": url, "auth": None}
    assert result.text == "hi"
    assert result.cost_usd is None


async def test_tc0110_compatible_server_gets_no_openrouter_only_fields() -> None:
    # KAI-5: Groq answered 400 to the OpenRouter-only "usage" field.
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "hi"}}]}
        )

    provider = OpenRouterProvider(
        "groq-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        url=chat_url("https://api.groq.com/openai/v1"),
    )
    await provider.complete(REQ, ROUTES["narrate"])

    assert "usage" not in seen
