"""Saved reports: one JSON file per answer, named by its id.

Reports are immutable once saved; a re-run produces a comparison, never an
edit. Ids are random and checked against a strict pattern before they touch
the filesystem.
"""

import re
import secrets
import threading
from pathlib import Path

from pydantic import BaseModel

from app.agent.analyst import Answer

REPORT_ID = re.compile(r"^[a-f0-9]{16}$")


class ReportSummary(BaseModel):
    """A saved report in a listing."""

    id: str
    question: str
    kind: str
    created_at: str


class ReportNotFoundError(Exception):
    """No saved report has this id."""


class ReportStore:
    """Reports under one directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()

    def _path(self, report_id: str) -> Path:
        if not REPORT_ID.fullmatch(report_id):
            raise ReportNotFoundError(report_id)
        return self.directory / f"{report_id}.json"

    def save(self, answer: Answer) -> Answer:
        """Store the answer under a new id and return it with the id set."""
        saved = answer.model_copy(update={"id": secrets.token_hex(8)})
        assert saved.id is not None  # noqa: S101 - just set
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self._path(saved.id)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(saved.model_dump_json(indent=1))
            tmp.replace(path)
        return saved

    def get(self, report_id: str) -> Answer:
        """The saved answer, or ReportNotFoundError."""
        path = self._path(report_id)
        if not path.is_file():
            raise ReportNotFoundError(report_id)
        return Answer.model_validate_json(path.read_text())

    def list(self, limit: int = 50) -> list[ReportSummary]:
        """Newest first."""
        if not self.directory.is_dir():
            return []
        answers = [Answer.model_validate_json(p.read_text()) for p in self.directory.glob("*.json")]
        answers.sort(key=lambda a: a.created_at, reverse=True)
        return [
            ReportSummary(
                id=a.id or "", question=a.question, kind=a.kind, created_at=a.created_at.isoformat()
            )
            for a in answers[:limit]
        ]
