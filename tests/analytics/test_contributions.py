"""Contribution maths: exact sums (property tests) and cause versus bystander."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.analytics.contributions import Cell, decompose_counts, decompose_rates, rank_causes

SEGMENTS = ["a", "b", "c", "d"]


@st.composite
def rate_period(draw: st.DrawFn) -> dict[str, Cell]:
    present = draw(st.lists(st.sampled_from(SEGMENTS), min_size=1, max_size=4, unique=True))
    cells: dict[str, Cell] = {}
    for segment in present:
        denominator = draw(st.integers(min_value=1, max_value=5_000))
        cells[segment] = Cell(draw(st.integers(min_value=0, max_value=denominator)), denominator)
    return cells


@st.composite
def count_period(draw: st.DrawFn) -> dict[str, Cell]:
    present = draw(st.lists(st.sampled_from(SEGMENTS), min_size=1, max_size=4, unique=True))
    return {s: Cell(draw(st.integers(min_value=0, max_value=10_000))) for s in present}


def _overall(cells: dict[str, Cell]) -> float:
    return sum(c.numerator for c in cells.values()) / sum(c.size for c in cells.values())


@given(rate_period(), rate_period())
def test_tc0040_rate_contributions_sum_to_the_total_change(
    baseline: dict[str, Cell], current: dict[str, Cell]
) -> None:
    rows = decompose_rates(baseline, current)

    assert sum(r.contribution for r in rows) == pytest.approx(
        _overall(current) - _overall(baseline), abs=1e-9
    )


@given(count_period(), count_period())
def test_tc0041_count_contributions_sum_to_the_total_change(
    baseline: dict[str, Cell], current: dict[str, Cell]
) -> None:
    rows = decompose_counts(baseline, current)

    total = sum(c.numerator for c in current.values()) - sum(c.numerator for c in baseline.values())
    assert sum(r.contribution for r in rows) == total


def test_tc0042_a_new_segment_contributes_through_mix_only() -> None:
    baseline = {"old": Cell(600, 1000)}
    current = {"old": Cell(300, 500), "new": Cell(150, 500)}

    new = next(r for r in decompose_rates(baseline, current) if r.segment == "new")

    assert new.baseline_value is None
    assert new.rate_effect == 0.0
    assert new.mix_effect == pytest.approx(0.5 * (0.3 - 0.6))


def test_tc0043_cause_beats_bystander_and_complement() -> None:
    # A broken version takes over; phones are 85% of every version.
    baseline = {"v_old": Cell(5600, 10000)}
    current = {"v_old": Cell(1120, 2000), "v_new": Cell(2400, 8000)}

    ranked = rank_causes(decompose_rates(baseline, current))

    assert [r.segment for r in ranked if r.likely_cause] == ["v_new"]


def test_tc0043_healthy_complement_is_not_a_cause() -> None:
    baseline = {"healthy": Cell(5600, 9000), "broken": Cell(300, 1000)}
    current = {"healthy": Cell(1120, 2000), "broken": Cell(2400, 8000)}

    rows = {r.segment: r for r in decompose_rates(baseline, current)}

    assert rows["broken"].likely_cause
    assert not rows["healthy"].likely_cause
    assert rows["healthy"].separation_z < 0


def test_tc0044_uniform_growth_names_no_cause() -> None:
    baseline = {"a": Cell(1000), "b": Cell(500), "c": Cell(250)}
    current = {"a": Cell(1200), "b": Cell(600), "c": Cell(300)}

    assert not any(r.likely_cause for r in decompose_counts(baseline, current))


def test_tc0045_one_source_tripling_is_the_cause_of_a_lift() -> None:
    baseline = {"organic": Cell(1000), "tiktok": Cell(100), "referral": Cell(300)}
    current = {"organic": Cell(1010), "tiktok": Cell(300), "referral": Cell(295)}

    causes = [r.segment for r in rank_causes(decompose_counts(baseline, current)) if r.likely_cause]

    assert causes == ["tiktok"]
