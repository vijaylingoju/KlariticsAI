"""The five capabilities against a store small enough to check by hand (see conftest).

Test ids trace to docs/testing/test-cases.md.
"""

from datetime import date

import pytest

from app.analytics.errors import (
    AnalyticsError,
    CohortTooRecentError,
    EventNotTrackedError,
    InvalidArgumentError,
    InvalidDateRangeError,
    InvalidFilterError,
)
from app.analytics.models import (
    CompareQuery,
    CountMetric,
    CountQuery,
    DateRange,
    FunnelQuery,
    RetentionQuery,
)
from app.analytics.service import AnalyticsService

D1, D3, D10 = date(2026, 1, 1), date(2026, 1, 3), date(2026, 1, 10)
FUNNEL = ["product_viewed", "add_to_cart", "checkout_started", "purchase_completed"]


def test_tc0010_list_events_returns_catalogue_dimensions_and_range(
    tiny_service: AnalyticsService,
) -> None:
    catalog = tiny_service.list_events()

    names = {e.name: e for e in catalog.events}
    assert len(names) == 8
    assert names["signup"].unique_users == 4
    assert names["session_start"].total_events == 9
    assert (catalog.dataset_start, catalog.dataset_end) == (D1, D10)
    assert {d.name: d.values for d in catalog.dimensions}["country"] == ["BR", "US"]


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.count_events(CountQuery(event="refund_issued", start=D1, end=D10)),
        lambda s: s.funnel(FunnelQuery(steps=["add_to_cart", "refund_issued"], start=D1, end=D10)),
        lambda s: s.retention(
            RetentionQuery(cohort_start=D1, cohort_end=D3, return_event="refund_issued")
        ),
        lambda s: s.compare_segments(
            CompareQuery(
                metric=CountMetric(event="refund_issued"),
                current=DateRange(start=D3, end=D10),
                baseline=DateRange(start=D1, end=D1),
            )
        ),
    ],
    ids=["count", "funnel", "retention", "compare"],
)
def test_tc0011_untracked_event_is_reported_as_not_tracked(
    tiny_service: AnalyticsService, call: object
) -> None:
    with pytest.raises(EventNotTrackedError) as caught:
        call(tiny_service)  # type: ignore[operator]  # parametrized callables

    assert caught.value.code == "not_tracked"
    assert caught.value.details["event"] == "refund_issued"


def test_tc0011_not_tracked_suggests_the_closest_names(tiny_service: AnalyticsService) -> None:
    with pytest.raises(EventNotTrackedError) as caught:
        tiny_service.check_event("purchase")

    assert caught.value.details["closest_tracked"] == ["purchase_completed"]


def test_tc0012_counts_events_and_unique_users(tiny_service: AnalyticsService) -> None:
    events = tiny_service.count_events(CountQuery(event="session_start", start=D1, end=D10))
    users = tiny_service.count_events(
        CountQuery(event="session_start", start=D1, end=D10, measure="users")
    )

    assert events.total == 9
    assert users.total == 4


def test_tc0013_day_series_fills_days_without_events(tiny_service: AnalyticsService) -> None:
    result = tiny_service.count_events(
        CountQuery(event="session_start", start=D1, end=date(2026, 1, 7), interval="day")
    )

    assert [p.value for p in result.series] == [2, 3, 1, 1, 0, 0, 0]


def test_tc0013_week_series_starts_on_monday(tiny_service: AnalyticsService) -> None:
    result = tiny_service.count_events(
        CountQuery(event="session_start", start=D1, end=D10, interval="week")
    )

    assert [(p.period, p.value) for p in result.series] == [
        (date(2025, 12, 29), 7),
        (date(2026, 1, 5), 2),
    ]


def test_tc0014_group_by_and_filters(tiny_service: AnalyticsService) -> None:
    grouped = tiny_service.count_events(
        CountQuery(event="session_start", start=D1, end=D10, group_by="country")
    )
    android = tiny_service.count_events(
        CountQuery(event="session_start", start=D1, end=D10, filters={"os": ["Android"]})
    )

    assert [(g.segment, g.value) for g in grouped.groups] == [("BR", 5), ("US", 4)]
    assert android.total == 7
    assert android.filters == {"os": ["Android"]}


def test_tc0015_group_by_with_a_series_is_refused(tiny_service: AnalyticsService) -> None:
    with pytest.raises(InvalidArgumentError):
        tiny_service.count_events(
            CountQuery(event="session_start", start=D1, end=D10, interval="day", group_by="os")
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [(D10, D1), (date(2025, 12, 31), D3), (D1, date(2026, 1, 11))],
    ids=["reversed", "before-data", "after-data"],
)
def test_tc0016_dates_outside_or_reversed_are_refused(
    tiny_service: AnalyticsService, start: date, end: date
) -> None:
    with pytest.raises(InvalidDateRangeError):
        tiny_service.count_events(CountQuery(event="signup", start=start, end=end))


def test_tc0017_unknown_filter_value_lists_valid_values(tiny_service: AnalyticsService) -> None:
    with pytest.raises(InvalidFilterError) as caught:
        tiny_service.count_events(
            CountQuery(event="signup", start=D1, end=D10, filters={"country": ["Brazil"]})
        )

    assert caught.value.details["valid"] == ["BR", "US"]


def test_tc0020_funnel_counts_ordered_steps_inside_the_window(
    tiny_service: AnalyticsService,
) -> None:
    result = tiny_service.funnel(FunnelQuery(steps=FUNNEL, start=D1, end=D10))

    assert [s.users for s in result.steps] == [4, 2, 2, 1]
    assert [s.conversion_from_previous for s in result.steps] == [1.0, 0.5, 1.0, 0.5]
    assert result.overall_conversion == 0.25


def test_tc0020_a_longer_window_admits_later_steps(tiny_service: AnalyticsService) -> None:
    result = tiny_service.funnel(FunnelQuery(steps=FUNNEL, start=D1, end=D10, window_hours=48))

    assert [s.users for s in result.steps] == [4, 3, 2, 1]


def test_tc0022_funnel_segments_split_the_entering_users(tiny_service: AnalyticsService) -> None:
    result = tiny_service.funnel(FunnelQuery(steps=FUNNEL, start=D1, end=D10, group_by="os"))

    assert [(g.segment, g.entered, g.completed, g.conversion) for g in result.groups] == [
        ("Android", 3, 1, 0.3333),
        ("iOS", 1, 0, 0.0),
    ]


def test_tc0030_day_n_retention_by_hand(tiny_service: AnalyticsService) -> None:
    result = tiny_service.retention(RetentionQuery(cohort_start=D1, cohort_end=D3, days=[1, 7]))

    assert result.cohort_users == 4
    assert [(d.day, d.eligible_users, d.retained_users, d.retention) for d in result.days] == [
        (1, 4, 3, 0.75),
        (7, 4, 2, 0.5),
    ]


def test_tc0030_retention_per_segment(tiny_service: AnalyticsService) -> None:
    result = tiny_service.retention(
        RetentionQuery(cohort_start=D1, cohort_end=D3, days=[1, 7], group_by="country")
    )

    assert [(g.segment, [d.retention for d in g.days]) for g in result.groups] == [
        ("BR", [1.0, 0.5]),
        ("US", [0.5, 0.5]),
    ]


def test_tc0031_cohort_too_recent_for_day_n_is_refused(tiny_service: AnalyticsService) -> None:
    with pytest.raises(CohortTooRecentError) as caught:
        tiny_service.retention(
            RetentionQuery(cohort_start=D1, cohort_end=date(2026, 1, 4), days=[7])
        )

    assert caught.value.details["latest_cohort_end"] == "2026-01-03"


def test_tc0018_every_error_serialises_with_code_and_retryable(
    tiny_service: AnalyticsService,
) -> None:
    with pytest.raises(AnalyticsError) as caught:
        tiny_service.check_range(D10, D1)

    assert set(caught.value.as_dict()) == {"code", "message", "retryable", "details"}
