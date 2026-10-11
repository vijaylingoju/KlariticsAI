"""The DuckDB event store: schema, connections and the dataset's date range.

The seeder writes the file once; every analytics query opens it read-only.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR PRIMARY KEY,
    signup_ts TIMESTAMP NOT NULL,
    os VARCHAR NOT NULL,
    country VARCHAR NOT NULL,
    device VARCHAR NOT NULL,
    acquisition_source VARCHAR NOT NULL,
    signup_app_version VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    event_id BIGINT NOT NULL,
    user_id VARCHAR NOT NULL,
    event_name VARCHAR NOT NULL,
    ts TIMESTAMP NOT NULL,
    app_version VARCHAR NOT NULL,
    os VARCHAR NOT NULL,
    country VARCHAR NOT NULL,
    device VARCHAR NOT NULL,
    acquisition_source VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS events_name_ts ON events (event_name, ts);
CREATE INDEX IF NOT EXISTS events_user ON events (user_id);
"""


@dataclass(frozen=True)
class DatasetInfo:
    """What the store holds: its first and last day and the seed that built it."""

    start: date
    end: date
    seed: int


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the tables; safe to call on an existing store."""
    con.execute(SCHEMA)


def create_indexes(con: duckdb.DuckDBPyConnection) -> None:
    """Indexes are built after bulk loading, which is faster than before."""
    con.execute(INDEXES)


def write_meta(con: duckdb.DuckDBPyConnection, info: DatasetInfo) -> None:
    """Record the dataset range so tools can validate dates without scanning events."""
    rows = [
        ("start", info.start.isoformat()),
        ("end", info.end.isoformat()),
        ("seed", str(info.seed)),
    ]
    con.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", rows)


def read_meta(con: duckdb.DuckDBPyConnection) -> DatasetInfo:
    """Read the dataset range; raises LookupError on a store the seeder did not finish."""
    values = dict(con.execute("SELECT key, value FROM meta").fetchall())
    missing = {"start", "end", "seed"} - values.keys()
    if missing:
        msg = f"store is missing meta keys: {sorted(missing)}"
        raise LookupError(msg)
    return DatasetInfo(
        start=date.fromisoformat(values["start"]),
        end=date.fromisoformat(values["end"]),
        seed=int(values["seed"]),
    )


def connect_read_only(path: Path) -> duckdb.DuckDBPyConnection:
    """Open an existing store for queries; fails if the file is absent."""
    if not path.is_file():
        msg = f"event store not found at {path}; run `make seed`"
        raise FileNotFoundError(msg)
    return duckdb.connect(str(path), read_only=True)
