"""Which model serves each feature, with what caps, at what price.

Kept in code rather than YAML: three routes do not justify a parser
dependency, and mypy checks them. Prices are USD per million tokens
(OpenRouter's list price for the model).
"""

from dataclasses import dataclass

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


def check_routes() -> None:
    """Fail at import if a route breaks the caps or names a model without a price."""
    for route in ROUTES.values():
        if not 0 < route.max_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError(f"route {route.feature}: max_tokens {route.max_tokens} outside 1..600")
        if route.model not in PRICES:
            raise ValueError(f"route {route.feature}: no price for {route.model}")


check_routes()
