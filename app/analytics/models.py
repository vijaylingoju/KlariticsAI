"""Typed inputs and outputs of the five analytics capabilities.

Inputs forbid unknown fields; every field is described for a model reader,
because these schemas become the MCP tool schemas.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.catalog import DIMENSIONS, Dimension

Filters = Annotated[
    dict[Dimension, list[str]],
    Field(
        description=(
            "Keep only events whose dimension value is in the list, e.g. "
            '{"os": ["Android"], "country": ["BR"]}. Empty means no filter.'
        ),
    ),
]
Measure = Literal["events", "users"]


class Strict(BaseModel):
    """Base for inputs: unknown fields are an error, not ignored."""

    model_config = ConfigDict(extra="forbid")


class DateRange(Strict):
    """An inclusive range of calendar days (UTC)."""

    start: date = Field(description="First day, inclusive (YYYY-MM-DD).")
    end: date = Field(description="Last day, inclusive (YYYY-MM-DD).")


# ---------- list_events ----------


class EventInfo(BaseModel):
    """One tracked event."""

    name: str
    description: str
    total_events: int
    unique_users: int


class DimensionInfo(BaseModel):
    """One dimension and every value it takes in the data."""

    name: Dimension
    description: str
    values: list[str]


class EventCatalog(BaseModel):
    """Everything that is tracked, and the dataset's date range."""

    dataset_start: date
    dataset_end: date
    events: list[EventInfo]
    dimensions: list[DimensionInfo]


# ---------- count_events ----------


class CountQuery(Strict):
    """Count one event over a date range."""

    event: str = Field(description="Tracked event name, from list_events.")
    start: date = Field(description="First day, inclusive.")
    end: date = Field(description="Last day, inclusive.")
    measure: Measure = Field("events", description="events = occurrences; users = unique users.")
    interval: Literal["total", "day", "week"] = Field(
        "total", description="total, or a series per day or per ISO week (Monday start)."
    )
    filters: Filters = Field(default_factory=dict)
    group_by: Dimension | None = Field(
        None,
        description="Split the total by this dimension. Not combined with a day or week series.",
    )


class PeriodValue(BaseModel):
    """A value for one day or week."""

    period: date
    value: int


class SegmentValue(BaseModel):
    """A value for one dimension value."""

    segment: str
    value: int


class CountResult(BaseModel):
    """Counts for one event."""

    event: str
    measure: Measure
    start: date
    end: date
    filters: dict[str, list[str]]
    total: int
    series: list[PeriodValue] = Field(default_factory=list)
    groups: list[SegmentValue] = Field(default_factory=list)


# ---------- funnel ----------


class FunnelQuery(Strict):
    """Ordered conversion through 2 to 6 events."""

    steps: list[str] = Field(
        min_length=2,
        max_length=6,
        description="Tracked event names in order, e.g. checkout_started then purchase_completed.",
    )
    start: date = Field(description="First day users may enter the funnel (first step), inclusive.")
    end: date = Field(description="Last day users may enter the funnel, inclusive.")
    window_hours: int = Field(
        24,
        ge=1,
        le=24 * 14,
        description="Each later step must happen within this many hours of the first step.",
    )
    filters: Filters = Field(default_factory=dict)
    group_by: Dimension | None = Field(
        None, description="Split conversion by this dimension of the first step."
    )


class FunnelStep(BaseModel):
    """Users reaching one step."""

    event: str
    users: int
    conversion_from_previous: float
    conversion_from_first: float


class FunnelSegment(BaseModel):
    """Overall conversion for one dimension value."""

    segment: str
    entered: int
    completed: int
    conversion: float


class FunnelResult(BaseModel):
    """Step counts and conversion rates."""

    steps: list[FunnelStep]
    start: date
    end: date
    window_hours: int
    filters: dict[str, list[str]]
    overall_conversion: float
    groups: list[FunnelSegment] = Field(default_factory=list)


# ---------- retention ----------


class RetentionQuery(Strict):
    """Day-N retention of a cohort."""

    cohort_start: date = Field(description="First day of the cohort's start event, inclusive.")
    cohort_end: date = Field(description="Last day of the cohort's start event, inclusive.")
    days: list[int] = Field(
        default_factory=lambda: [1, 7],
        min_length=1,
        max_length=4,
        description="Which Day-N values to compute, each 1 to 30, e.g. [1, 7].",
    )
    start_event: str = Field(
        "signup", description="Event that puts a user in the cohort (first occurrence)."
    )
    return_event: str = Field("session_start", description="Event that counts as coming back.")
    filters: Filters = Field(default_factory=dict)
    group_by: Dimension | None = Field(None, description="Split retention by this dimension.")


class RetentionDay(BaseModel):
    """Retention on one day after the start event."""

    day: int
    eligible_users: int
    retained_users: int
    retention: float


class RetentionSegment(BaseModel):
    """Retention for one dimension value."""

    segment: str
    cohort_users: int
    days: list[RetentionDay]


class RetentionResult(BaseModel):
    """A cohort's Day-N retention."""

    cohort_start: date
    cohort_end: date
    start_event: str
    return_event: str
    filters: dict[str, list[str]]
    cohort_users: int
    days: list[RetentionDay]
    groups: list[RetentionSegment] = Field(default_factory=list)


# ---------- compare_segments ----------


class CountMetric(Strict):
    """Event volume."""

    kind: Literal["count"] = "count"
    event: str = Field(description="Tracked event name.")
    measure: Measure = "events"


class ConversionMetric(Strict):
    """Conversion from the first to the last step."""

    kind: Literal["conversion"] = "conversion"
    steps: list[str] = Field(
        min_length=2, max_length=6, description="Tracked event names in order."
    )
    window_hours: int = Field(24, ge=1, le=24 * 14)


class RetentionMetric(Strict):
    """Day-N retention; the periods are cohort ranges."""

    kind: Literal["retention"] = "retention"
    day: int = Field(7, ge=1, le=30, description="N in Day-N retention.")
    start_event: str = "signup"
    return_event: str = "session_start"


Metric = Annotated[CountMetric | ConversionMetric | RetentionMetric, Field(discriminator="kind")]


class CompareQuery(Strict):
    """Compare a metric between two periods and attribute the change to segments."""

    metric: Metric
    current: DateRange = Field(description="The period being explained.")
    baseline: DateRange = Field(description="The period to compare against, usually just before.")
    dimensions: list[Dimension] = Field(
        default_factory=lambda: list(DIMENSIONS),
        min_length=1,
        description="Dimensions to drill into. Default: all five.",
    )
    filters: Filters = Field(default_factory=dict)
    top_n: int = Field(5, ge=1, le=20, description="How many top contributing segments to return.")


class PeriodSummary(BaseModel):
    """The metric over one whole period."""

    value: float
    numerator: int
    denominator: int | None


class SegmentChange(BaseModel):
    """One segment's values and its contribution to the total change.

    For rates, contribution = rate_effect + mix_effect, and contributions across
    one dimension sum to the total change. For counts, contribution is the
    segment's own change and mix_effect is 0.
    """

    dimension: Dimension
    segment: str
    baseline_value: float | None = Field(
        description="None when the segment did not exist in the baseline."
    )
    current_value: float | None = Field(
        description="None when the segment does not exist in the current period."
    )
    change: float | None
    baseline_size: int
    current_size: int
    rate_effect: float
    mix_effect: float
    contribution: float
    share_of_change: float
    explained: float = Field(
        description=(
            "Share of the total change that disappears when this segment is removed from both "
            "periods. Near 1: this segment alone accounts for the change. Near 0: the rest "
            "changed just as much, so it is a bystander."
        )
    )
    separation_z: float = Field(
        description=(
            "How far this segment stands apart from all other segments, in the direction of the "
            "change, as a z-score. Above 3 is a clear difference; negative means it moved the "
            "other way."
        )
    )
    likely_cause: bool = Field(
        description=(
            "True when the segment carries the change, explains it (>= 0.5) "
            "and stands apart (z >= 3)."
        )
    )


class DimensionBreakdown(BaseModel):
    """All segments of one dimension, largest contribution first."""

    dimension: Dimension
    explained_by_top_segment: float = Field(
        description="The highest `explained` of any segment in this dimension."
    )
    segments: list[SegmentChange]


class CompareResult(BaseModel):
    """The change and where it came from."""

    metric: CountMetric | ConversionMetric | RetentionMetric
    current: PeriodSummary
    baseline: PeriodSummary
    change: float
    relative_change: float | None
    filters: dict[str, list[str]]
    breakdowns: list[DimensionBreakdown]
    top_contributors: list[SegmentChange] = Field(
        description=(
            "Likely causes first (highest `explained`), then the largest carriers of the change."
        )
    )
