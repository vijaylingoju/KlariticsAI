"""A persisted record of every model call and what it cost, with a hard spend limit.

One JSON line per call, appended and flushed before the response is used, so
a crash never loses spend. The total is read back on start: the limit holds
across restarts, not just within one process.
"""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from app.llm.types import BudgetExceededError


class LedgerEntry(BaseModel):
    """One call: who asked, which model answered, the tokens and the cost."""

    at: datetime
    feature: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    stop_reason: str
    replayed: bool


class Ledger:
    """Spend so far and the limit it must stay under. Thread-safe."""

    def __init__(self, path: Path, limit_usd: float) -> None:
        self.path = path
        self.limit_usd = limit_usd
        self._lock = threading.Lock()
        self._spent = 0.0
        self._calls = 0
        if path.is_file():
            for line in path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._spent += 0.0 if row.get("replayed") else float(row["cost_usd"])
                    self._calls += 1

    @property
    def spent_usd(self) -> float:
        """Total recorded cost."""
        return self._spent

    @property
    def calls(self) -> int:
        """Recorded calls."""
        return self._calls

    def check(self, worst_case_usd: float) -> None:
        """Refuse a call that could take spend past the limit."""
        with self._lock:
            if self._spent + worst_case_usd > self.limit_usd:
                raise BudgetExceededError(
                    "spend limit reached",
                    spent_usd=round(self._spent, 6),
                    limit_usd=self.limit_usd,
                    worst_case_usd=round(worst_case_usd, 6),
                )

    def record(self, entry: LedgerEntry) -> None:
        """Append one call. Replayed calls cost nothing new and do not count against the limit."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as fh:
                fh.write(entry.model_dump_json() + "\n")
            if not entry.replayed:
                self._spent += entry.cost_usd
            self._calls += 1


def now() -> datetime:
    """The wall clock, in one place so tests can see where time enters."""
    return datetime.now(UTC)
