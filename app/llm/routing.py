"""Which model serves each feature, with what caps, at what price.

Kept in code rather than YAML: three routes do not justify a parser
dependency, and mypy checks them. Prices are USD per million tokens
(OpenRouter's list price for the model).
"""

from dataclasses import dataclass, replace

from app.llm.types import Feature

HAIKU = "anthropic/claude-haiku-4.5"
# The brief caps every call at 600 output tokens; routes may ask for less, never more.
MAX_OUTPUT_TOKENS = 600


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input_per_m: float
    output_per_m: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        """USD for this many tokens."""
        return (input_tokens * self.input_per_m + output_tokens * self.output_per_m) / 1_000_000


@dataclass(frozen=True)
class Route:
    """How one feature calls the model."""

    feature: Feature
    model: str
    max_tokens: int
    timeout_s: float


PRICES: dict[str, Price] = {HAIKU: Price(input_per_m=1.00, output_per_m=5.00)}

ROUTES: dict[Feature, Route] = {
    "intent_parse": Route("intent_parse", HAIKU, max_tokens=500, timeout_s=30),
    "investigate": Route("investigate", HAIKU, max_tokens=400, timeout_s=30),
    "narrate": Route("narrate", HAIKU, max_tokens=400, timeout_s=30),
}


def configure_model(
    model: str | None,
    input_per_m: float | None = None,
    output_per_m: float | None = None,
    timeout_s: float | None = None,
) -> tuple[dict[Feature, Route], dict[str, Price]]:
    """Routes and prices with every feature on `model` (LLM_MODEL); None keeps Haiku.

    A model without a list price here needs one from the caller, so the budget
    check never prices a paid model at zero. A local model is priced 0, 0.
    `timeout_s` (LLM_TIMEOUT_S) replaces every route's timeout: a local model
    on a laptop answers far slower than a hosted one.
    """
    routes = {f: replace(r, timeout_s=timeout_s or r.timeout_s) for f, r in ROUTES.items()}
    if model is None:
        return routes, dict(PRICES)
    prices = dict(PRICES)
    if input_per_m is not None and output_per_m is not None:
        prices[model] = Price(input_per_m=input_per_m, output_per_m=output_per_m)
    elif model not in prices:
        raise ValueError(
            f"LLM_MODEL {model} has no price: set LLM_PRICE_INPUT_PER_M and LLM_PRICE_OUTPUT_PER_M"
        )
    return {f: replace(r, model=model) for f, r in routes.items()}, prices


def check_routes() -> None:
    """Fail at import if a route breaks the caps or names a model without a price."""
    for route in ROUTES.values():
        if not 0 < route.max_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError(f"route {route.feature}: max_tokens {route.max_tokens} outside 1..600")
        if route.model not in PRICES:
            raise ValueError(f"route {route.feature}: no price for {route.model}")


check_routes()
