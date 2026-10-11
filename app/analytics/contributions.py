"""Attribute a metric's change between two periods to the segments of one dimension.

Three numbers per segment answer three different questions.

contribution: how much of the change does the segment carry? Counts add up, so
it is the segment's own change. Rates (conversion, retention) are weighted
averages, so it splits into a rate effect (the segment's own rate moved,
weighted by its baseline share) and a mix effect (its share moved, times how
far its rate sits from the baseline overall rate):

    rate_s = w0_s * (r1_s - r0_s)
    mix_s  = (w1_s - w0_s) * (r1_s - R0)

Summed over every segment of a dimension these equal R1 - R0 exactly. A segment
absent from one period takes its rate from the other, so a new app version that
converts badly shows up as a negative mix effect.

explained: would the change disappear without this segment? Contribution alone
cannot tell a cause from a bystander: when a new app version breaks checkout,
"phone" carries most of the drop simply because most users use phones. For
rates, explained = 1 - (change of the rate with the segment removed) / change.
For counts it compares growth: 1 - (growth of the rest) / (growth of the total).
A segment that is the whole population in either period gets 0.

separation_z: is the segment itself abnormal, in the direction of the change?
For rates, a two-proportion z of the segment against everyone else in the
current period; for counts, the z of the segment's log growth against the
rest's. Positive means it moved the way the total moved, harder than the rest.
This rules out the complement of a cause: when a broken version takes over,
removing the healthy version also "explains" the drop, but the healthy version
is better than the rest, not worse, so its separation is negative.

A segment is a likely cause when it carries the change (share_of_change > 0),
explains it (explained >= 0.5) and stands apart (separation_z >= 3).
"""

import math
from dataclasses import dataclass

CAUSE_MIN_EXPLAINED = 0.5
CAUSE_MIN_Z = 3.0


@dataclass(frozen=True)
class Cell:
    """A segment in one period: numerator and, for rates, denominator."""

    numerator: int
    denominator: int | None = None

    @property
    def size(self) -> int:
        """Users or events the segment carries in the period."""
        return self.denominator if self.denominator is not None else self.numerator


@dataclass(frozen=True)
class Contribution:
    """One segment's values and how well it accounts for the total change."""

    segment: str
    baseline_value: float | None
    current_value: float | None
    baseline_size: int
    current_size: int
    rate_effect: float
    mix_effect: float
    contribution: float
    share_of_change: float
    explained: float
    separation_z: float

    @property
    def likely_cause(self) -> bool:
        """Carries, explains and stands apart from the rest."""
        return (
            self.share_of_change > 0
            and self.explained >= CAUSE_MIN_EXPLAINED
            and self.separation_z >= CAUSE_MIN_Z
        )


def _sign(x: float) -> float:
    return 1.0 if x > 0 else -1.0 if x < 0 else 0.0


def _rate(cell: Cell | None) -> float | None:
    if cell is None or not cell.denominator:
        return None
    return cell.numerator / cell.denominator


def _sum(cells: list[Cell]) -> tuple[int, int]:
    return sum(c.numerator for c in cells), sum(c.size for c in cells)


def decompose_counts(baseline: dict[str, Cell], current: dict[str, Cell]) -> list[Contribution]:
    """Each segment's change in a count, largest absolute contribution first."""
    total0 = sum(c.numerator for c in baseline.values())
    total1 = sum(c.numerator for c in current.values())
    total_change = total1 - total0
    total_growth = (total1 - total0) / total0 if total0 else 0.0
    rows: list[Contribution] = []
    for segment in sorted(baseline.keys() | current.keys()):
        b = baseline.get(segment, Cell(0)).numerator
        c = current.get(segment, Cell(0)).numerator
        rest0, rest1 = total0 - b, total1 - c
        explained = 0.0
        z = 0.0
        if rest0 > 0 and rest1 > 0 and total_growth:
            explained = 1 - ((rest1 - rest0) / rest0) / total_growth
            # Log growth of the segment against the rest, with a 0.5 continuity correction.
            diff = math.log((c + 0.5) / (b + 0.5)) - math.log((rest1 + 0.5) / (rest0 + 0.5))
            se = math.sqrt(1 / (c + 0.5) + 1 / (b + 0.5) + 1 / (rest1 + 0.5) + 1 / (rest0 + 0.5))
            z = _sign(total_change) * diff / se
        rows.append(
            Contribution(
                segment=segment,
                baseline_value=float(b),
                current_value=float(c),
                baseline_size=b,
                current_size=c,
                rate_effect=float(c - b),
                mix_effect=0.0,
                contribution=float(c - b),
                share_of_change=(c - b) / total_change if total_change else 0.0,
                explained=explained,
                separation_z=z,
            )
        )
    rows.sort(key=lambda r: (-abs(r.contribution), r.segment))
    return rows


def _explained_rate(
    baseline: dict[str, Cell], current: dict[str, Cell], segment: str, total_change: float
) -> float:
    if not total_change:
        return 0.0
    n0, d0 = _sum([c for s, c in baseline.items() if s != segment])
    n1, d1 = _sum([c for s, c in current.items() if s != segment])
    if d0 == 0 or d1 == 0:
        return 0.0
    return 1 - (n1 / d1 - n0 / d0) / total_change


def _separation_rate(current: dict[str, Cell], segment: str, direction: float) -> float:
    cell = current.get(segment)
    if cell is None or not cell.size:
        return 0.0
    rest_n, rest_d = _sum([c for s, c in current.items() if s != segment])
    if rest_d == 0:
        return 0.0
    pooled = (cell.numerator + rest_n) / (cell.size + rest_d)
    se = math.sqrt(pooled * (1 - pooled) * (1 / cell.size + 1 / rest_d))
    if se == 0:
        return 0.0
    return direction * (cell.numerator / cell.size - rest_n / rest_d) / se


def decompose_rates(baseline: dict[str, Cell], current: dict[str, Cell]) -> list[Contribution]:
    """Rate and mix effects per segment, largest absolute contribution first."""
    n0, d0 = _sum(list(baseline.values()))
    n1, d1 = _sum(list(current.values()))
    if d0 == 0 or d1 == 0:
        return []
    overall0 = n0 / d0
    total_change = n1 / d1 - overall0
    direction = _sign(total_change)
    rows: list[Contribution] = []
    for segment in sorted(baseline.keys() | current.keys()):
        b, c = baseline.get(segment), current.get(segment)
        seen0, seen1 = _rate(b), _rate(c)
        r0 = seen0 if seen0 is not None else seen1
        r1 = seen1 if seen1 is not None else seen0
        if r0 is None or r1 is None:
            continue
        w0 = (b.size if b else 0) / d0
        w1 = (c.size if c else 0) / d1
        rate_effect = w0 * (r1 - r0)
        mix_effect = (w1 - w0) * (r1 - overall0)
        contribution = rate_effect + mix_effect
        rows.append(
            Contribution(
                segment=segment,
                baseline_value=seen0,
                current_value=seen1,
                baseline_size=b.size if b else 0,
                current_size=c.size if c else 0,
                rate_effect=rate_effect,
                mix_effect=mix_effect,
                contribution=contribution,
                share_of_change=contribution / total_change if total_change else 0.0,
                explained=_explained_rate(baseline, current, segment, total_change),
                separation_z=_separation_rate(current, segment, direction),
            )
        )
    rows.sort(key=lambda r: (-abs(r.contribution), r.segment))
    return rows


def rank_causes(rows: list[Contribution]) -> list[Contribution]:
    """Likely causes first (best explained), then the rest by share of change."""
    return sorted(
        rows,
        key=lambda r: (
            not r.likely_cause,
            -min(r.explained, 1.0) if r.likely_cause else -r.share_of_change,
            -r.separation_z,
            r.segment,
        ),
    )
