"""Every number in a narrative must come from tool evidence; sentences that fail are removed.

Evidence is every number in the tool results the answer rests on, plus what
a writer may fairly derive from them: rates as percentages, differences
(including percentage-point changes), relative changes and ratios between
values from the same result. A narrative number matches when it equals an
evidence number at the precision the narrative wrote it, so "62%" matches
0.6213 and "9.8 points" matches -0.0981 (sign is carried by the words).

Dates, app versions and day labels are not quantities and are not checked:
"Day-7", "2026-09-17" and "5.4.0" are names, and the intent fixed them.
"""

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

# A quantity: optional sign, digits with optional thousands commas and decimals, optional %.
NUMBER = re.compile(
    r"(?<![\w.])[-+\u2212]?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|(?<![\w.])[-+\u2212]?\d+(?:\.\d+)?%?"
)
# Spans that are names, not quantities: ISO dates, versions, Day-N, D7, N-day.
NOT_QUANTITY = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\b\d+\.\d+\.\d+\b"
    r"|\b[Dd]ay[- ]\d+\b|\bD\d+\b|\b\d+-day\b"
    r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? \d{1,2}\b"
    r"|\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\b"
)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
# Small counting words in prose ("two segments", "1 of 5") are allowed without evidence.
SMALL_INTEGERS = frozenset(range(11))


@dataclass
class Evidence:
    """The numbers an answer may state."""

    values: set[float] = field(default_factory=set)

    @classmethod
    def from_results(cls, results: Iterable[object]) -> Evidence:
        """Collect raw numbers from each result, then add derived ones within each result."""
        evidence = cls()
        for result in results:
            raw = sorted({abs(v) for v in _numbers(result)})
            evidence.values.update(raw)
            evidence.values.update(_derived(raw))
        return evidence

    def supports(self, written: float, decimals: int, percent: bool) -> bool:
        """Does any evidence number round to what was written?"""
        target = abs(written)
        tolerance = 0.5 * 10 ** (-decimals) + 1e-9
        for value in self.values:
            for scaled in (value * 100, value) if percent else (value, value * 100):
                if abs(scaled - target) <= tolerance:
                    return True
        return False


def _numbers(node: object) -> Iterable[float]:
    if isinstance(node, bool):
        return
    if isinstance(node, int | float):
        if math.isfinite(node):
            yield float(node)
    elif isinstance(node, dict):
        for value in node.values():
            yield from _numbers(value)
    elif isinstance(node, list):
        for value in node:
            yield from _numbers(value)


MAX_PAIRWISE = 400


def _derived(values: list[float]) -> set[float]:
    """Differences, ratios and relative changes between numbers of one result."""
    out: set[float] = set()
    pool = values[:MAX_PAIRWISE]
    for i, a in enumerate(pool):
        for b in pool[i + 1 :]:
            out.add(b - a)
            if a:
                out.add(b / a)
                out.add((b - a) / a)
            if b:
                out.add((b - a) / b)
    return out


@dataclass
class Checked:
    """The narrative after the check, and what was removed."""

    text: str
    removed: list[str]
    numbers_checked: int


def _quantities(sentence: str) -> list[tuple[float, int, bool]]:
    masked = NOT_QUANTITY.sub(lambda m: " " * len(m.group()), sentence)
    out: list[tuple[float, int, bool]] = []
    for match in NUMBER.finditer(masked):
        token = match.group().replace(",", "").replace("\u2212", "-")
        percent = token.endswith("%")
        digits = token.rstrip("%")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        out.append((float(digits), decimals, percent))
    return out


def check_narrative(text: str, evidence: Evidence) -> Checked:
    """Keep the sentences whose every number is supported; drop the rest."""
    kept: list[str] = []
    removed: list[str] = []
    checked = 0
    for sentence in SENTENCE.split(text.strip()):
        if not sentence:
            continue
        quantities = _quantities(sentence)
        checked += len(quantities)
        unsupported = [
            q
            for q in quantities
            if not (q[1] == 0 and not q[2] and q[0] in SMALL_INTEGERS)
            and not evidence.supports(q[0], q[1], q[2])
        ]
        (removed if unsupported else kept).append(sentence)
    return Checked(text=" ".join(kept), removed=removed, numbers_checked=checked)


def word_count(text: str) -> int:
    """Words, as a reader counts them."""
    return len(text.split())


def limit_words(text: str, limit: int) -> str:
    """Whole sentences up to `limit` words."""
    out: list[str] = []
    total = 0
    for sentence in SENTENCE.split(text.strip()):
        n = word_count(sentence)
        if total + n > limit:
            break
        out.append(sentence)
        total += n
    return " ".join(out)
