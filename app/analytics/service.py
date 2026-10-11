"""The five analytics capabilities over the DuckDB event store.

Every method validates its input against the catalogue and the dataset range
before any SQL runs, so a model gets a typed error it can act on instead of an
empty result. Column names in SQL come only from the fixed dimension list;
every value is a bound parameter.
"""

import difflib
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from threading import Lock

import duckdb

from app.analytics.catalog import DIMENSION_DESCRIPTIONS, DIMENSIONS, EVENTS, Dimension
from app.analytics.contributions import (
    Cell,
    Contribution,
    decompose_counts,
    decompose_rates,
    rank_causes,
)
from app.analytics.errors import (
    CohortTooRecentError,
    EventNotTrackedError,
    InvalidArgumentError,
    InvalidDateRangeError,
    InvalidFilterError,
)
from app.analytics.models import (
    CompareQuery,
    CompareResult,
    ConversionMetric,
    CountMetric,
    CountQuery,
    CountResult,
    DateRange,
    DimensionBreakdown,
    DimensionInfo,
    EventCatalog,
    EventInfo,
    FunnelQuery,
    FunnelResult,
    FunnelSegment,
    FunnelStep,
    PeriodSummary,
    PeriodValue,
    RetentionDay,
    RetentionMetric,
    RetentionQuery,
    RetentionResult,
    RetentionSegment,
    SegmentChange,
    SegmentValue,
)
from app.analytics.store import DatasetInfo, read_meta

Params = list[object]
ALL = "__all__"


def _round(value: float) -> float:
    return round(value, 4)


def _ratio(numerator: int, denominator: int) -> float:
    return _round(numerator / denominator) if denominator else 0.0


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Half-open timestamp bounds for an inclusive day range."""
    return datetime.combine(start, datetime.min.time()), datetime.combine(
        end + timedelta(days=1), datetime.min.time()
    )


class AnalyticsService:
    """Read-only analytics over one store. Safe to share across threads."""

    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self._con = con
        self._lock = Lock()
        self.info: DatasetInfo = read_meta(con)
        self._values: dict[Dimension, list[str]] = {
            dim: [
                str(row[0])
                for row in con.execute(
                    f"SELECT DISTINCT {dim} FROM events ORDER BY 1"  # noqa: S608 - dim from fixed list
                ).fetchall()
            ]
            for dim in DIMENSIONS
        }

    def ping(self) -> None:
        """Raise if the store cannot answer a trivial query."""
        self._rows("SELECT 1", [])

    # ---------- shared validation ----------

    def _rows(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        with self._lock:
            cursor = self._con.cursor()
            try:
                return cursor.execute(sql, list(params)).fetchall()
            finally:
                cursor.close()

    def check_event(self, name: str) -> None:
        """Raise `not_tracked` with the closest names when an event is unknown."""
        if name in EVENTS:
            return
        suggestions = difflib.get_close_matches(name, list(EVENTS), n=3, cutoff=0.4)
        raise EventNotTrackedError(
            f"event '{name}' is not tracked",
            details={"event": name, "closest_tracked": suggestions, "tracked": sorted(EVENTS)},
        )

    def check_range(self, start: date, end: date, label: str = "range") -> None:
        """Dates in order and inside the dataset."""
        if start > end:
            raise InvalidDateRangeError(
                f"{label}: start {start} is after end {end}", details={"start": start.isoformat()}
            )
        if start < self.info.start or end > self.info.end:
            raise InvalidDateRangeError(
                f"{label}: {start} to {end} is outside the data "
                f"({self.info.start} to {self.info.end})",
                details={
                    "dataset_start": self.info.start.isoformat(),
                    "dataset_end": self.info.end.isoformat(),
                },
            )

    def check_filters(self, filters: dict[Dimension, list[str]]) -> None:
        """Every filter value exists in the data."""
        for dim, values in filters.items():
            if not values:
                raise InvalidFilterError(
                    f"filter on {dim} has no values", details={"dimension": dim}
                )
            unknown = [v for v in values if v not in self._values[dim]]
            if unknown:
                raise InvalidFilterError(
                    f"unknown {dim} value(s): {unknown}",
                    details={"dimension": dim, "unknown": unknown, "valid": self._values[dim]},
                )

    @staticmethod
    def _filter_sql(filters: dict[Dimension, list[str]], alias: str = "") -> tuple[str, Params]:
        prefix = f"{alias}." if alias else ""
        clauses: list[str] = []
        params: Params = []
        for dim in DIMENSIONS:
            values = filters.get(dim)
            if values:
                clauses.append(f" AND {prefix}{dim} IN ({', '.join('?' for _ in values)})")
                params.extend(values)
        return "".join(clauses), params

    @staticmethod
    def _clean(filters: dict[Dimension, list[str]]) -> dict[str, list[str]]:
        return {dim: list(values) for dim, values in filters.items() if values}

    # ---------- list_events ----------

    def list_events(self) -> EventCatalog:
        """Every tracked event with volume, every dimension with its values."""
        stats = {
            str(name): (int(str(total)), int(str(users)))
            for name, total, users in self._rows(
                "SELECT event_name, count(*), count(DISTINCT user_id) FROM events GROUP BY 1", []
            )
        }
        return EventCatalog(
            dataset_start=self.info.start,
            dataset_end=self.info.end,
            events=[
                EventInfo(
                    name=name,
                    description=description,
                    total_events=stats.get(name, (0, 0))[0],
                    unique_users=stats.get(name, (0, 0))[1],
                )
                for name, description in EVENTS.items()
            ],
            dimensions=[
                DimensionInfo(
                    name=dim, description=DIMENSION_DESCRIPTIONS[dim], values=self._values[dim]
                )
                for dim in DIMENSIONS
            ],
        )

    # ---------- count_events ----------

    def count_events(self, q: CountQuery) -> CountResult:
        """Total, series or per-segment counts of one event."""
        self.check_event(q.event)
        self.check_range(q.start, q.end)
        self.check_filters(q.filters)
        if q.group_by and q.interval != "total":
            raise InvalidArgumentError(
                "group_by cannot be combined with a day or week series; make two calls",
                details={"group_by": q.group_by, "interval": q.interval},
            )
        lo, hi = _bounds(q.start, q.end)
        where, fparams = self._filter_sql(q.filters)
        agg = "count(*)" if q.measure == "events" else "count(DISTINCT user_id)"
        base = f"FROM events WHERE event_name = ? AND ts >= ? AND ts < ?{where}"
        params: Params = [q.event, lo, hi, *fparams]
        total = int(str(self._rows(f"SELECT {agg} {base}", params)[0][0]))
        result = CountResult(
            event=q.event,
            measure=q.measure,
            start=q.start,
            end=q.end,
            filters=self._clean(q.filters),
            total=total,
        )
        if q.interval != "total":
            unit = "day" if q.interval == "day" else "week"
            rows = self._rows(
                f"SELECT CAST(date_trunc('{unit}', ts) AS DATE) AS p, {agg} {base} "
                "GROUP BY 1 ORDER BY 1",
                params,
            )
            found = {r[0]: int(str(r[1])) for r in rows}
            periods = self._periods(q.start, q.end, unit)
            result.series = [PeriodValue(period=p, value=found.get(p, 0)) for p in periods]
        if q.group_by:
            rows = self._rows(
                f"SELECT {q.group_by}, {agg} {base} GROUP BY 1 ORDER BY 2 DESC, 1",
                params,
            )
            result.groups = [SegmentValue(segment=str(r[0]), value=int(str(r[1]))) for r in rows]
        return result

    @staticmethod
    def _periods(start: date, end: date, unit: str) -> list[date]:
        if unit == "day":
            return [start + timedelta(days=i) for i in range((end - start).days + 1)]
        first = start - timedelta(days=start.weekday())
        return [first + timedelta(weeks=i) for i in range((end - first).days // 7 + 1)]

    # ---------- funnel ----------

    def _funnel_counts(
        self,
        steps: Sequence[str],
        start: date,
        end: date,
        window_hours: int,
        filters: dict[Dimension, list[str]],
        group_by: Dimension | None,
    ) -> dict[str, list[int]]:
        """Users reaching each step, per segment (or under ALL)."""
        lo, hi = _bounds(start, end)
        where, fparams = self._filter_sql(filters)
        seg = f"arg_min({group_by}, ts)" if group_by else f"'{ALL}'"
        ctes = [
            f"s0 AS (SELECT user_id, min(ts) AS t0, min(ts) AS t, {seg} AS seg FROM events "  # noqa: S608
            f"WHERE event_name = ? AND ts >= ? AND ts < ?{where} GROUP BY user_id)"
        ]
        params: Params = [steps[0], lo, hi, *fparams]
        for i, step in enumerate(steps[1:], start=1):
            ctes.append(
                f"s{i} AS (SELECT p.user_id, p.t0, min(e.ts) AS t FROM s{i - 1} p "  # noqa: S608 - CTE names only
                f"JOIN events e ON e.user_id = p.user_id AND e.event_name = ? "
                f"AND e.ts > p.t AND e.ts <= p.t0 + to_hours(?) GROUP BY p.user_id, p.t0)"
            )
            params.extend([step, window_hours])
        joins = "".join(f" LEFT JOIN s{i} USING (user_id)" for i in range(1, len(steps)))
        counts = ", ".join(f"count(s{i}.user_id)" for i in range(len(steps)))
        sql = f"WITH {', '.join(ctes)} SELECT s0.seg, {counts} FROM s0{joins} GROUP BY 1 ORDER BY 1"  # noqa: S608
        return {str(r[0]): [int(str(v)) for v in r[1:]] for r in self._rows(sql, params)}

    def _check_steps(self, steps: Sequence[str]) -> None:
        for step in steps:
            self.check_event(step)

    def funnel(self, q: FunnelQuery) -> FunnelResult:
        """Ordered conversion, optionally split by a dimension of the first step."""
        self._check_steps(q.steps)
        self.check_range(q.start, q.end)
        self.check_filters(q.filters)
        overall = self._funnel_counts(q.steps, q.start, q.end, q.window_hours, q.filters, None)
        counts = overall.get(ALL, [0] * len(q.steps))
        first = counts[0]
        steps = [
            FunnelStep(
                event=name,
                users=n,
                conversion_from_previous=_ratio(n, counts[i - 1]) if i else 1.0,
                conversion_from_first=_ratio(n, first),
            )
            for i, (name, n) in enumerate(zip(q.steps, counts, strict=True))
        ]
        result = FunnelResult(
            steps=steps,
            start=q.start,
            end=q.end,
            window_hours=q.window_hours,
            filters=self._clean(q.filters),
            overall_conversion=_ratio(counts[-1], first),
        )
        if q.group_by:
            per = self._funnel_counts(
                q.steps, q.start, q.end, q.window_hours, q.filters, q.group_by
            )
            result.groups = sorted(
                (
                    FunnelSegment(
                        segment=s, entered=c[0], completed=c[-1], conversion=_ratio(c[-1], c[0])
                    )
                    for s, c in per.items()
                ),
                key=lambda g: (-g.entered, g.segment),
            )
        return result

    # ---------- retention ----------

    def _check_cohort(self, cohort_start: date, cohort_end: date, max_day: int) -> None:
        self.check_range(cohort_start, cohort_end, "cohort")
        latest = self.info.end - timedelta(days=max_day)
        if cohort_end > latest:
            raise CohortTooRecentError(
                f"Day-{max_day} is not observable yet for cohorts after {latest}",
                details={"latest_cohort_end": latest.isoformat(), "day": max_day},
            )

    def _retention_counts(
        self,
        cohort_start: date,
        cohort_end: date,
        days: Sequence[int],
        start_event: str,
        return_event: str,
        filters: dict[Dimension, list[str]],
        group_by: Dimension | None,
    ) -> dict[str, tuple[int, dict[int, tuple[int, int]]]]:
        """Per segment: cohort size and, per day, (eligible, retained)."""
        where, fparams = self._filter_sql(filters)
        seg = f"arg_min({group_by}, ts)" if group_by else f"'{ALL}'"
        values = ", ".join("(?)" for _ in days)
        sql = (
            f"WITH cohort AS (SELECT user_id, CAST(min(ts) AS DATE) AS d0, {seg} AS seg "  # noqa: S608
            f"FROM events WHERE event_name = ?{where} GROUP BY user_id "
            "HAVING CAST(min(ts) AS DATE) BETWEEN ? AND ?), "
            "back AS (SELECT DISTINCT user_id, CAST(ts AS DATE) AS d FROM events "
            "WHERE event_name = ? AND ts >= ?), "
            f"n(day) AS (VALUES {values}) "
            "SELECT c.seg, n.day, count(*) AS eligible, count(b.user_id) AS retained, "
            "(SELECT count(*) FROM cohort c2 WHERE c2.seg = c.seg) AS size "
            "FROM cohort c CROSS JOIN n "
            "LEFT JOIN back b ON b.user_id = c.user_id AND b.d = c.d0 + n.day "
            "WHERE c.d0 + n.day <= ? GROUP BY 1, 2 ORDER BY 1, 2"
        )
        lo, _ = _bounds(cohort_start, cohort_end)
        params: Params = [
            start_event,
            *fparams,
            cohort_start,
            cohort_end,
            return_event,
            lo,
            *days,
            self.info.end,
        ]
        out: dict[str, tuple[int, dict[int, tuple[int, int]]]] = {}
        for segment, day, eligible, retained, size in self._rows(sql, params):
            key = str(segment)
            _, per_day = out.setdefault(key, (int(str(size)), {}))
            per_day[int(str(day))] = (int(str(eligible)), int(str(retained)))
        return out

    @staticmethod
    def _days(days: Sequence[int], per_day: dict[int, tuple[int, int]]) -> list[RetentionDay]:
        rows: list[RetentionDay] = []
        for d in days:
            eligible, retained = per_day.get(d, (0, 0))
            rows.append(
                RetentionDay(
                    day=d,
                    eligible_users=eligible,
                    retained_users=retained,
                    retention=_ratio(retained, eligible),
                )
            )
        return rows

    def retention(self, q: RetentionQuery) -> RetentionResult:
        """Day-N retention of the users whose start event falls in the cohort range."""
        self.check_event(q.start_event)
        self.check_event(q.return_event)
        days = sorted(set(q.days))
        if any(d < 1 or d > 30 for d in days):
            raise InvalidArgumentError("each day must be between 1 and 30", details={"days": days})
        self._check_cohort(q.cohort_start, q.cohort_end, max(days))
        self.check_filters(q.filters)
        overall = self._retention_counts(
            q.cohort_start, q.cohort_end, days, q.start_event, q.return_event, q.filters, None
        )
        size, per_day = overall.get(ALL, (0, {}))
        result = RetentionResult(
            cohort_start=q.cohort_start,
            cohort_end=q.cohort_end,
            start_event=q.start_event,
            return_event=q.return_event,
            filters=self._clean(q.filters),
            cohort_users=size,
            days=self._days(days, per_day),
        )
        if q.group_by:
            per = self._retention_counts(
                q.cohort_start,
                q.cohort_end,
                days,
                q.start_event,
                q.return_event,
                q.filters,
                q.group_by,
            )
            result.groups = sorted(
                (
                    RetentionSegment(segment=s, cohort_users=n, days=self._days(days, pd))
                    for s, (n, pd) in per.items()
                ),
                key=lambda g: (-g.cohort_users, g.segment),
            )
        return result

    # ---------- compare_segments ----------

    def _cells(
        self,
        metric: CountMetric | ConversionMetric | RetentionMetric,
        period: DateRange,
        filters: dict[Dimension, list[str]],
        group_by: Dimension | None,
    ) -> dict[str, Cell]:
        if isinstance(metric, CountMetric):
            q = CountQuery(
                event=metric.event,
                start=period.start,
                end=period.end,
                measure=metric.measure,
                filters=filters,
                group_by=group_by,
            )
            counted = self.count_events(q)
            if group_by is None:
                return {ALL: Cell(counted.total)}
            return {g.segment: Cell(g.value) for g in counted.groups}
        if isinstance(metric, ConversionMetric):
            per = self._funnel_counts(
                metric.steps, period.start, period.end, metric.window_hours, filters, group_by
            )
            return {s: Cell(c[-1], c[0]) for s, c in per.items()}
        per_ret = self._retention_counts(
            period.start,
            period.end,
            [metric.day],
            metric.start_event,
            metric.return_event,
            filters,
            group_by,
        )
        return {
            s: Cell(pd.get(metric.day, (0, 0))[1], pd.get(metric.day, (0, 0))[0])
            for s, (_, pd) in per_ret.items()
        }

    def _validate_metric(
        self, metric: CountMetric | ConversionMetric | RetentionMetric, periods: Sequence[DateRange]
    ) -> None:
        if isinstance(metric, CountMetric):
            self.check_event(metric.event)
        elif isinstance(metric, ConversionMetric):
            self._check_steps(metric.steps)
        else:
            self.check_event(metric.start_event)
            self.check_event(metric.return_event)
        for label, period in zip(("current", "baseline"), periods, strict=True):
            if isinstance(metric, RetentionMetric):
                self._check_cohort(period.start, period.end, metric.day)
            else:
                self.check_range(period.start, period.end, label)

    @staticmethod
    def _summary(cells: dict[str, Cell], is_rate: bool) -> PeriodSummary:
        cell = cells.get(ALL, Cell(0, 0 if is_rate else None))
        if is_rate:
            return PeriodSummary(
                value=_ratio(cell.numerator, cell.denominator or 0),
                numerator=cell.numerator,
                denominator=cell.denominator or 0,
            )
        return PeriodSummary(
            value=float(cell.numerator), numerator=cell.numerator, denominator=None
        )

    @staticmethod
    def _segment(dim: Dimension, c: Contribution, is_rate: bool) -> SegmentChange:
        b = None if c.baseline_value is None else _round(c.baseline_value)
        n = None if c.current_value is None else _round(c.current_value)
        return SegmentChange(
            dimension=dim,
            segment=c.segment,
            baseline_value=b if is_rate or c.baseline_size else (b if b is not None else 0.0),
            current_value=n if is_rate or c.current_size else (n if n is not None else 0.0),
            change=None if b is None or n is None else _round(n - b),
            baseline_size=c.baseline_size,
            current_size=c.current_size,
            rate_effect=_round(c.rate_effect),
            mix_effect=_round(c.mix_effect),
            contribution=_round(c.contribution),
            share_of_change=_round(c.share_of_change),
            explained=_round(c.explained),
            separation_z=round(c.separation_z, 2),
            likely_cause=c.likely_cause,
        )

    def compare_segments(self, q: CompareQuery) -> CompareResult:
        """The metric in both periods and each segment's contribution to the change."""
        self._validate_metric(q.metric, [q.current, q.baseline])
        self.check_filters(q.filters)
        is_rate = not isinstance(q.metric, CountMetric)
        current = self._summary(self._cells(q.metric, q.current, q.filters, None), is_rate)
        baseline = self._summary(self._cells(q.metric, q.baseline, q.filters, None), is_rate)
        change = _round(current.value - baseline.value)
        breakdowns: list[DimensionBreakdown] = []
        everything: list[tuple[Dimension, Contribution]] = []
        for dim in dict.fromkeys(q.dimensions):
            cur = self._cells(q.metric, q.current, q.filters, dim)
            base = self._cells(q.metric, q.baseline, q.filters, dim)
            parts = decompose_rates(base, cur) if is_rate else decompose_counts(base, cur)
            breakdowns.append(
                DimensionBreakdown(
                    dimension=dim,
                    explained_by_top_segment=_round(
                        max((c.explained for c in parts if c.likely_cause), default=0.0)
                    ),
                    segments=[self._segment(dim, c, is_rate) for c in parts],
                )
            )
            everything.extend((dim, c) for c in parts)
        ranked = rank_causes([c for _, c in everything])
        dims = {id(c): d for d, c in everything}
        top = [self._segment(dims[id(c)], c, is_rate) for c in ranked if c.share_of_change > 0][
            : q.top_n
        ]
        return CompareResult(
            metric=q.metric,
            current=current,
            baseline=baseline,
            change=change,
            relative_change=_round(change / baseline.value) if baseline.value else None,
            filters=self._clean(q.filters),
            breakdowns=breakdowns,
            top_contributors=top,
        )
