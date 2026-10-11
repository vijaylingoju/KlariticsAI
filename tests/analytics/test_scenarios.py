"""compare_segments finds each planted cause on the full store and nothing else (US-02-005).

These are the questions the analyst will be asked, answered by the
deterministic attribution alone; the agent's fallback relies on them.
Test ids trace to docs/testing/test-cases.md.
"""

from datetime import date, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.analytics.models import (
    CompareQuery,
    CompareResult,
    ConversionMetric,
    CountMetric,
    DateRange,
    FunnelQuery,
    RetentionMetric,
    RetentionQuery,
)
from app.analytics.service import AnalyticsService
from app.seed import scenarios as sc

PURCHASE = ["checkout_started", "purchase_completed"]


def _range(start: str, end: str) -> DateRange:
    return DateRange(start=date.fromisoformat(start), end=date.fromisoformat(end))


def _causes(result: CompareResult) -> set[tuple[str, str]]:
    return {
        (s.dimension, s.segment) for b in result.breakdowns for s in b.segments if s.likely_cause
    }


def test_tc0050_purchase_drop_is_attributed_to_the_new_version(service: AnalyticsService) -> None:
    query = CompareQuery(
        metric=ConversionMetric(steps=PURCHASE),
        current=_range("2026-09-24", "2026-09-30"),
        baseline=_range("2026-09-03", "2026-09-09"),
    )

    result = service.compare_segments(query)

    assert result.change < 0
    assert _causes(result) == {("app_version", sc.FUNNEL_DROP_VERSION)}
    assert (result.top_contributors[0].dimension, result.top_contributors[0].segment) == (
        "app_version",
        sc.FUNNEL_DROP_VERSION,
    )


def test_tc0051_d7_retention_drop_last_week_is_attributed_to_the_country(
    service: AnalyticsService,
) -> None:
    query = CompareQuery(
        metric=RetentionMetric(day=7),
        current=_range("2026-09-17", "2026-09-23"),
        baseline=_range("2026-09-10", "2026-09-16"),
    )

    result = service.compare_segments(query)

    assert result.change < 0
    assert _causes(result) == {("country", sc.RETENTION_COUNTRY)}


def test_tc0052_android_d7_drop_is_attributed_to_the_country(service: AnalyticsService) -> None:
    # The brief's example: "Why did Day-7 retention drop for Android users last week?"
    query = CompareQuery(
        metric=RetentionMetric(day=7),
        current=_range("2026-09-17", "2026-09-23"),
        baseline=_range("2026-09-10", "2026-09-16"),
        filters={"os": ["Android"]},
    )

    result = service.compare_segments(query)

    assert result.change < 0
    assert result.filters == {"os": ["Android"]}
    assert _causes(result) == {("country", sc.RETENTION_COUNTRY)}


def test_tc0053_signup_lift_is_attributed_to_the_campaign_source(service: AnalyticsService) -> None:
    query = CompareQuery(
        metric=CountMetric(event="signup"),
        current=_range("2026-08-26", "2026-09-04"),
        baseline=_range("2026-08-16", "2026-08-25"),
    )

    result = service.compare_segments(query)

    assert result.change > 0
    assert _causes(result) == {("acquisition_source", sc.CAMPAIGN_SOURCE)}


def test_tc0054_quiet_period_names_no_cause(service: AnalyticsService) -> None:
    # Before any version 5.4.0 user exists and away from the campaign window.
    query = CompareQuery(
        metric=ConversionMetric(steps=PURCHASE),
        current=_range("2026-09-01", "2026-09-07"),
        baseline=_range("2026-08-25", "2026-08-31"),
    )

    result = service.compare_segments(query)

    assert _causes(result) == set()


def test_tc0055_contributions_in_each_dimension_sum_to_the_change(
    service: AnalyticsService,
) -> None:
    query = CompareQuery(
        metric=ConversionMetric(steps=PURCHASE),
        current=_range("2026-09-17", "2026-09-30"),
        baseline=_range("2026-09-03", "2026-09-16"),
        top_n=20,
    )

    result = service.compare_segments(query)

    sums = {b.dimension: sum(s.contribution for s in b.segments) for b in result.breakdowns}
    # Each segment is rounded to 4 places, so allow that rounding per segment.
    assert sums == pytest.approx(dict.fromkeys(sums, result.change), abs=1e-3)


days = st.integers(min_value=0, max_value=(sc.END - sc.START).days)


@settings(
    max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(a=days, b=days)
def test_tc0021_funnel_step_counts_never_increase(
    service: AnalyticsService, a: int, b: int
) -> None:
    start, end = sc.START + timedelta(days=min(a, b)), sc.START + timedelta(days=max(a, b))

    result = service.funnel(
        FunnelQuery(
            steps=["product_viewed", "add_to_cart", "checkout_started", "purchase_completed"],
            start=start,
            end=end,
        )
    )

    users = [s.users for s in result.steps]
    assert users == sorted(users, reverse=True)


@settings(
    max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(a=st.integers(min_value=0, max_value=45), length=st.integers(min_value=0, max_value=6))
def test_tc0032_retention_is_a_share_of_eligible_users(
    service: AnalyticsService, a: int, length: int
) -> None:
    start = sc.START + timedelta(days=a)

    result = service.retention(
        RetentionQuery(cohort_start=start, cohort_end=start + timedelta(days=length), days=[1, 7])
    )

    assert all(
        0 <= d.retained_users <= d.eligible_users <= result.cohort_users for d in result.days
    )
    assert all(0.0 <= d.retention <= 1.0 for d in result.days)
