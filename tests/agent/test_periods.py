"""Relative periods resolve against the last day of data (AC-US-04-001-3)."""

from datetime import date

import pytest

from app.agent.periods import PeriodSpec, Window, cohort_window, previous, resolve

FIRST, LAST = date(2026, 8, 2), date(2026, 9, 30)


def _w(a: str, b: str) -> Window:
    return Window(start=date.fromisoformat(a), end=date.fromisoformat(b))


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (PeriodSpec(kind="last_week"), _w("2026-09-24", "2026-09-30")),
        (PeriodSpec(kind="last_n_days", n=14), _w("2026-09-17", "2026-09-30")),
        (PeriodSpec(kind="this_month"), _w("2026-09-01", "2026-09-30")),
        (PeriodSpec(kind="last_month"), _w("2026-08-02", "2026-08-31")),
        (
            PeriodSpec(kind="between", start=date(2026, 8, 26), end=date(2026, 9, 4)),
            _w("2026-08-26", "2026-09-04"),
        ),
        (PeriodSpec(kind="since", start=date(2026, 9, 11)), _w("2026-09-11", "2026-09-30")),
        (PeriodSpec(kind="all"), _w("2026-08-02", "2026-09-30")),
        (PeriodSpec(kind="unspecified"), _w("2026-09-24", "2026-09-30")),
    ],
    ids=[
        "last_week",
        "last_14_days",
        "this_month",
        "last_month_clamped",
        "between",
        "since",
        "all",
        "default",
    ],
)
def test_tc0200_relative_periods_resolve_against_the_last_day(
    spec: PeriodSpec, expected: Window
) -> None:
    assert resolve(spec, FIRST, LAST) == expected


def test_tc0201_day7_last_week_means_the_latest_observable_cohorts() -> None:
    window = cohort_window(PeriodSpec(kind="last_week"), FIRST, LAST, day=7)

    assert window == _w("2026-09-17", "2026-09-23")


def test_tc0201_explicit_cohorts_are_cut_where_day_n_is_unobservable() -> None:
    window = cohort_window(PeriodSpec(kind="since", start=date(2026, 9, 20)), FIRST, LAST, day=7)

    assert window == _w("2026-09-20", "2026-09-23")


def test_tc0202_baseline_is_the_equal_length_range_before() -> None:
    assert previous(_w("2026-09-17", "2026-09-23"), FIRST) == _w("2026-09-10", "2026-09-16")


@pytest.mark.parametrize(
    "call",
    [
        lambda: resolve(
            PeriodSpec(kind="between", start=date(2025, 1, 1), end=date(2025, 2, 1)), FIRST, LAST
        ),
        lambda: previous(_w("2026-08-02", "2026-08-08"), FIRST),
    ],
    ids=["outside_data", "nothing_before"],
)
def test_tc0203_periods_outside_the_data_are_refused(call: object) -> None:
    with pytest.raises(ValueError, match=r"outside the data|no data before"):
        call()  # type: ignore[operator]  # parametrised lambdas


@pytest.mark.parametrize(
    "payload",
    [{"kind": "last_n_days"}, {"kind": "between", "start": "2026-09-01"}, {"kind": "since"}],
    ids=["n", "end", "start"],
)
def test_tc0203_incomplete_period_is_invalid(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="needs"):
        PeriodSpec.model_validate(payload)
