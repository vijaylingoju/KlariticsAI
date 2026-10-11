"""Numbers in a narrative must come from evidence (US-05-001)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.guardrails.numbers import Evidence, check_narrative, limit_words

EVIDENCE = Evidence.from_results(
    [
        {
            "baseline_value": 0.6213,
            "current_value": 0.5233,
            "change": -0.098,
            "users": 12840,
            "ratio_base": 1300,
        }
    ]
)


@pytest.mark.parametrize(
    "sentence",
    [
        "Conversion fell from 62.1% to 52.3%.",
        "Conversion fell from 62% to 52%.",
        "That is a drop of 9.8 points.",
        "It fell by 0.098.",
        "12,840 users entered checkout.",
        "The drop is 15.8% in relative terms.",
        "Users outnumber the base 9.9 times.",
    ],
    ids=["rates_1dp", "rates_0dp", "points", "raw_change", "count_commas", "relative", "ratio"],
)
def test_tc0300_supported_numbers_are_kept(sentence: str) -> None:
    checked = check_narrative(sentence, EVIDENCE)

    assert (checked.text, checked.removed) == (sentence, [])


@pytest.mark.parametrize(
    "sentence",
    [
        "Conversion fell to 41.0%.",
        "That is a drop of 12.5 points.",
        "13,500 users entered checkout.",
    ],
    ids=["rate", "points", "count"],
)
def test_tc0301_unsupported_number_removes_its_sentence(sentence: str) -> None:
    text = f"Conversion fell on the newest version. {sentence} Other versions held steady."

    checked = check_narrative(text, EVIDENCE)

    assert checked.removed == [sentence]
    assert checked.text == "Conversion fell on the newest version. Other versions held steady."


def test_tc0302_dates_versions_and_day_labels_are_not_quantities() -> None:
    text = "Day-7 retention for cohorts from 2026-09-17 on app 5.4.0 and D7 users fell from Sep 10."

    checked = check_narrative(text, Evidence())

    assert checked.removed == []


def test_tc0302_small_counting_words_need_no_evidence() -> None:
    assert check_narrative("Two of 5 dimensions moved.", Evidence()).removed == []


def test_tc0303_words_are_capped_at_whole_sentences() -> None:
    text = "One two three four. Five six seven eight. Nine ten."

    assert limit_words(text, 9) == "One two three four. Five six seven eight."


@given(st.floats(min_value=0.001, max_value=0.999, allow_nan=False))
def test_tc0304_any_rate_written_as_a_percentage_is_supported(rate: float) -> None:
    evidence = Evidence.from_results([{"value": rate}])

    checked = check_narrative(f"The rate is {rate * 100:.1f}%.", evidence)

    assert checked.removed == []
