"""Typed analytics errors. Each has a stable code a model or a client can act on."""

from collections.abc import Mapping


class AnalyticsError(Exception):
    """A request the analytics layer cannot answer, with a machine-readable code."""

    code = "analytics_error"
    retryable = False

    def __init__(self, message: str, *, details: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, object] = dict(details or {})

    def as_dict(self) -> dict[str, object]:
        """The structured error a tool returns."""
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


class EventNotTrackedError(AnalyticsError):
    """The event name is not in the catalogue."""

    code = "not_tracked"


class InvalidDateRangeError(AnalyticsError):
    """Dates are reversed or outside the dataset."""

    code = "invalid_date_range"


class InvalidFilterError(AnalyticsError):
    """A filter names an unknown value."""

    code = "invalid_filter"


class InvalidArgumentError(AnalyticsError):
    """Arguments are individually valid but cannot be combined."""

    code = "invalid_argument"


class CohortTooRecentError(AnalyticsError):
    """Day-N is past the end of the data for part of the cohort."""

    code = "cohort_too_recent"
