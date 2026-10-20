"""`Gateway.complete`: the only path from this service to a model.

kill switch -> route -> budget check (worst case) -> provider, one retry
on a transient failure -> price from usage -> ledger -> one log line.

Nothing outside `app/llm/` talks to a provider. Logs carry tokens, cost
and timing, never prompt or completion text.
"""

import asyncio
import json
import math
import os
import random
import time
from collections.abc import Awaitable, Callable, Mapping

import structlog

from app.core.config import Settings
from app.llm.ledger import Ledger, LedgerEntry, now
from app.llm.providers import (
    OPENROUTER_URL,
    OpenRouterProvider,
    Provider,
    RecordingProvider,
    ReplayProvider,
    chat_url,
    wire_body,
)
from app.llm.routing import PRICES, ROUTES, Price, Route, configure_model
from app.llm.types import (
    Feature,
    FeatureDisabledError,
    LLMRequest,
    LLMResponse,
    ProviderRejectedError,
    ProviderUnavailableError,
)

log = structlog.get_logger()

# Longest wait a provider's Retry-After can impose before the one retry.
MAX_RETRY_WAIT_S = 60.0


def _retry_wait(attempt: int, retry_after_s: object) -> float:
    """Back off with jitter, or as long as the provider asked, up to the cap."""
    backoff = 0.5 * attempt + random.random() * 0.5  # noqa: S311 - jitter, not security
    if isinstance(retry_after_s, int | float):
        return min(max(backoff, float(retry_after_s)), MAX_RETRY_WAIT_S)
    return backoff


# Conservative: JSON-heavy prompts run near 3.5 characters per token.
CHARS_PER_TOKEN = 3


def worst_case_cost(req: LLMRequest, route: Route, price: Price | None = None) -> float:
    """USD if the prompt is as long as it could be and the answer uses every output token."""
    body = wire_body(req, route)
    input_tokens = math.ceil(len(json.dumps(body)) / CHARS_PER_TOKEN)
    return (price or PRICES[route.model]).cost(input_tokens, body["max_tokens"])


def killed_features() -> frozenset[str]:
    """Features switched off with LLM_KILL_<FEATURE>=1."""
    return frozenset(
        name.removeprefix("LLM_KILL_").lower()
        for name, value in os.environ.items()
        if name.startswith("LLM_KILL_") and value == "1"
    )


class Gateway:
    """Routes, caps, prices and records every model call."""

    def __init__(
        self,
        provider: Provider,
        ledger: Ledger,
        *,
        disabled: frozenset[str] = frozenset(),
        retries: int = 1,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        routes: Mapping[Feature, Route] = ROUTES,
        prices: Mapping[str, Price] = PRICES,
    ) -> None:
        self.provider = provider
        self.routes = routes
        self.prices = prices
        self.ledger = ledger
        self.disabled = disabled
        self.retries = retries
        self._sleep = sleep

    async def complete(self, req: LLMRequest) -> LLMResponse:
        """One model call, refused before sending when disabled or over budget."""
        route = self.routes[req.feature]
        if req.feature in self.disabled:
            raise FeatureDisabledError("feature disabled", feature=req.feature)
        self.ledger.check(worst_case_cost(req, route, self.prices[route.model]))
        started = time.monotonic()
        attempt = 0
        while True:
            try:
                result = await self.provider.complete(req, route)
                break
            except ProviderRejectedError as exc:
                log.warning("llm rejected", feature=req.feature, **exc.details)
                raise
            except ProviderUnavailableError as exc:
                if attempt >= self.retries:
                    log.warning(
                        "llm unavailable", feature=req.feature, attempts=attempt + 1, **exc.details
                    )
                    raise
                attempt += 1
                await self._sleep(_retry_wait(attempt, exc.details.get("retry_after_s")))
        latency_ms = int((time.monotonic() - started) * 1000)
        price = self.prices.get(result.model) or self.prices[route.model]
        cost = (
            result.cost_usd
            if result.cost_usd is not None
            else price.cost(result.usage.input_tokens, result.usage.output_tokens)
        )
        self.ledger.record(
            LedgerEntry(
                at=now(),
                feature=req.feature,
                model=result.model or route.model,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
                stop_reason=result.stop_reason,
                replayed=result.replayed,
            )
        )
        log.info(
            "llm call",
            feature=req.feature,
            model=result.model or route.model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost_usd=round(cost, 6),
            latency_ms=latency_ms,
            stop_reason=result.stop_reason,
            replayed=result.replayed,
            spent_usd=round(self.ledger.spent_usd, 4),
        )
        return LLMResponse(
            text=result.text,
            tool_calls=result.tool_calls,
            stop_reason=result.stop_reason,
            model=result.model or route.model,
            usage=result.usage,
            cost_usd=cost,
            latency_ms=latency_ms,
            replayed=result.replayed,
        )


def build_provider(
    mode: str, api_key: str | None, recordings: ReplayProvider, url: str = OPENROUTER_URL
) -> Provider:
    """live calls the model at `url`; record calls it and saves; replay never leaves the process."""
    if mode == "replay":
        return recordings
    live = OpenRouterProvider(api_key, url=url)
    return RecordingProvider(live, recordings) if mode == "record" else live


def gateway_from_settings(
    settings: Settings, mode: str, ledger: Ledger, disabled: frozenset[str] = frozenset()
) -> Gateway:
    """The gateway the settings describe: model, endpoint, key and recordings."""
    key = settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else None
    routes, prices = configure_model(
        settings.llm_model,
        settings.llm_price_input_per_m,
        settings.llm_price_output_per_m,
        settings.llm_timeout_s,
    )
    provider = build_provider(
        mode, key, ReplayProvider(settings.llm_recordings_dir), chat_url(settings.llm_base_url)
    )
    return Gateway(provider, ledger, disabled=disabled, routes=routes, prices=prices)
