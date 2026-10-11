"""Turn a period as people say it ("last week", "the past 10 days") into dates.

The model only names the kind of period; dates are computed here, against
the last day of data rather than the wall clock, so the same question gets
the same dates in every run and every eval.

Conventions, stated in every answer that uses them:
- "last week" is the latest seven days with data; "last N days" likewise.
- For Day-N retention the period is a cohort range, and the latest cohorts
  whose Day N is observable end N days before the last day of data.
- With no baseline named, the baseline is the equal-length range just before.
"""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator

PeriodKind = Literal[
    "last_week", "last_n_days", "this_month", "last_month", "between", "since", "all", "unspecified"
]


class PeriodSpec(BaseModel):
    """A period as the question states it."""

    kind: PeriodKind = Field(
        description=(
            "last_week: the latest 7 days. last_n_days: the latest n days. "
            "this_month / last_month: calendar months of the data. "
            "between: explicit start and end. since: from start to the "
            "last day. all: the whole dataset. unspecified: the question names no period."
        )
    )
    n: int | None = Field(None, ge=1, le=60, description="Days, for last_n_days.")
    start: date | None = Field(None, description="For between and since.")
    end: date | None = Field(None, description="For between.")

    @model_validator(mode="after")
    def _needs(self) -> PeriodSpec:
        if self.kind == "last_n_days" and self.n is None:
            raise ValueError("last_n_days needs n")
        if self.kind in ("between", "since") and self.start is None:
            raise ValueError(f"{self.kind} needs start")
        if self.kind == "between" and self.end is None:
            raise ValueError("between needs end")
        return self


class Window(BaseModel):
    """Resolved dates, inclusive."""

    start: date
    end: date

    @property
    def days(self) -> int:
        """Number of days in the window."""
        return (self.end - self.start).days + 1

    def label(self) -> str:
        """2026-09-24 to 2026-09-30."""
        return f"{self.start.isoformat()} to {self.end.isoformat()}"


def _clamp(start: date, end: date, first: date, last: date) -> Window:
    start, end = max(start, first), min(end, last)
    if start > end:
        raise ValueError(f"{start} to {end} is outside the data ({first} to {last})")
    return Window(start=start, end=end)


def resolve(spec: PeriodSpec, first: date, last: date, *, default_days: int = 7) -> Window:
    """Dates for a period, inside the data. `last` stands for 'today'."""
    match spec.kind:
        case "last_week":
            return _clamp(last - timedelta(days=6), last, first, last)
        case "last_n_days":
            assert spec.n is not None  # noqa: S101 - guaranteed by the validator
            return _clamp(last - timedelta(days=spec.n - 1), last, first, last)
        case "this_month":
            return _clamp(last.replace(day=1), last, first, last)
        case "last_month":
            end = last.replace(day=1) - timedelta(days=1)
            return _clamp(end.replace(day=1), end, first, last)
        case "between":
            assert spec.start is not None  # noqa: S101
            assert spec.end is not None  # noqa: S101
            return _clamp(spec.start, spec.end, first, last)
        case "since":
            assert spec.start is not None  # noqa: S101
            return _clamp(spec.start, last, first, last)
        case "all":
            return Window(start=first, end=last)
        case "unspecified":
            return _clamp(last - timedelta(days=default_days - 1), last, first, last)


def cohort_window(spec: PeriodSpec, first: date, last: date, day: int) -> Window:
    """A cohort range whose Day-N is observable: relative periods shift back by N days."""
    observable = last - timedelta(days=day)
    if spec.kind in ("between", "since", "all"):
        window = resolve(spec, first, last)
        return _clamp(window.start, min(window.end, observable), first, observable)
    return resolve(spec, first, observable)


def previous(window: Window, first: date) -> Window:
    """The equal-length range just before `window`."""
    end = window.start - timedelta(days=1)
    start = end - timedelta(days=window.days - 1)
    if end < first:
        raise ValueError(f"no data before {window.start} to compare with")
    return Window(start=max(start, first), end=end)
