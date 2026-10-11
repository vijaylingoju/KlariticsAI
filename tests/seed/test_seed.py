"""The seeded store: shape, determinism and the three planted scenarios (US-01-001, US-01-002).

Scenario checks read the store with plain SQL, independent of the analytics
service, so a bug in the service cannot hide a bug in the seeder.
Test ids trace to docs/testing/test-cases.md.
"""

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from app.analytics.catalog import DIMENSIONS, EVENTS
from app.seed import scenarios as sc
from app.seed.generator import seed


@pytest.fixture(scope="module")
def con(store_path: Path) -> duckdb.DuckDBPyConnection:
    """A read-only SQL connection to the full store."""
    return duckdb.connect(str(store_path), read_only=True)


def _one(
    con: duckdb.DuckDBPyConnection, sql: str, params: list[object] | None = None
) -> tuple[object, ...]:
    row = con.execute(sql, params or []).fetchone()
    assert row is not None
    return row


def _conversion(con: duckdb.DuckDBPyConnection, where: str, start: date, end: date) -> float:
    """Checkout-to-purchase within 24h for checkouts between start and end, by plain SQL."""
    row = _one(
        con,
        f"""
        WITH c AS (
            SELECT user_id, min(ts) AS t0, arg_min(app_version, ts) AS app_version
            FROM events WHERE event_name = 'checkout_started' AND ts::DATE BETWEEN ? AND ?
            GROUP BY user_id
        )
        SELECT count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM events p WHERE p.user_id = c.user_id
                   AND p.event_name = 'purchase_completed'
                   AND p.ts >= c.t0 AND p.ts <= c.t0 + INTERVAL 24 HOUR)) / count(*)
        FROM c WHERE {where}
        """,  # noqa: S608 - `where` is a literal from this file
        [start, end],
    )
    return float(str(row[0]))


def _d7(con: duckdb.DuckDBPyConnection, where: str, start: date, end: date) -> float:
    """Share of users signing up between start and end with a session exactly 7 days later."""
    row = _one(
        con,
        f"""
        WITH c AS (SELECT user_id, signup_ts::DATE AS d0, country FROM users
                   WHERE signup_ts::DATE BETWEEN ? AND ?)
        SELECT avg(CASE WHEN EXISTS (
                   SELECT 1 FROM events e WHERE e.user_id = c.user_id
                   AND e.event_name = 'session_start' AND e.ts::DATE = c.d0 + 7) THEN 1 ELSE 0 END)
        FROM c WHERE {where}
        """,  # noqa: S608 - `where` is a literal from this file
        [start, end],
    )
    return float(str(row[0]))


def _daily_signups(con: duckdb.DuckDBPyConnection, where: str, start: date, end: date) -> float:
    row = _one(
        con,
        f"SELECT count(*) / (? - ? + 1) FROM users "  # noqa: S608 - `where` is a literal from this file
        f"WHERE signup_ts::DATE BETWEEN ? AND ? AND {where}",
        [end, start, start, end],
    )
    return float(str(row[0]))


def test_tc0001_store_holds_20000_users_over_60_days(con: duckdb.DuckDBPyConnection) -> None:
    (users,) = _one(con, "SELECT count(*) FROM users")
    first, last = _one(con, "SELECT min(ts)::DATE, max(ts)::DATE FROM events")

    assert users == sc.USERS
    assert (first, last) == (sc.START, sc.END)
    assert (sc.END - sc.START).days + 1 == sc.DAYS


def test_tc0002_every_row_carries_all_dimensions_and_a_catalogue_event(
    con: duckdb.DuckDBPyConnection,
) -> None:
    dims = " OR ".join(f"{d} IS NULL OR {d} = ''" for d in DIMENSIONS)
    names = ", ".join(f"'{name}'" for name in EVENTS)

    (bad_dims,) = _one(con, f"SELECT count(*) FROM events WHERE {dims}")  # noqa: S608 - catalogue literals
    (bad_names,) = _one(con, f"SELECT count(*) FROM events WHERE event_name NOT IN ({names})")  # noqa: S608
    (orphans,) = _one(con, "SELECT count(*) FROM events e ANTI JOIN users u USING (user_id)")

    assert (bad_dims, bad_names, orphans) == (0, 0, 0)


def test_tc0003_same_seed_gives_identical_stores(tmp_path: Path) -> None:
    a, b = tmp_path / "a.duckdb", tmp_path / "b.duckdb"
    sql = "SELECT ts::DATE AS d, event_name, count(*) FROM events GROUP BY ALL ORDER BY ALL"

    seed(a, seed_value=7, users=300)
    seed(b, seed_value=7, users=300)

    with duckdb.connect(str(a), read_only=True) as ca, duckdb.connect(str(b), read_only=True) as cb:
        assert ca.execute(sql).fetchall() == cb.execute(sql).fetchall()


def test_tc0004_funnel_drop_hits_only_the_planted_version(con: duckdb.DuckDBPyConnection) -> None:
    release = sc.RELEASES[2][1]
    after = (release, sc.END)

    broken = _conversion(con, f"app_version = '{sc.FUNNEL_DROP_VERSION}'", *after)
    others_after = _conversion(con, f"app_version <> '{sc.FUNNEL_DROP_VERSION}'", *after)
    others_before = _conversion(con, "true", date(2026, 8, 20), date(2026, 9, 10))

    assert others_after - broken >= 0.15
    assert abs(others_after - others_before) < 0.03


def test_tc0005_retention_declines_only_in_the_planted_country(
    con: duckdb.DuckDBPyConnection,
) -> None:
    week, prior = (date(2026, 9, 17), date(2026, 9, 23)), (date(2026, 9, 10), date(2026, 9, 16))
    country = f"country = '{sc.RETENTION_COUNTRY}'"
    rest = f"country <> '{sc.RETENTION_COUNTRY}'"

    planted_drop = _d7(con, country, *prior) - _d7(con, country, *week)
    rest_move = _d7(con, rest, *week) - _d7(con, rest, *prior)

    assert planted_drop >= 0.10
    assert abs(rest_move) < 0.03


def test_tc0006_campaign_lifts_only_the_planted_source(con: duckdb.DuckDBPyConnection) -> None:
    campaign = (sc.CAMPAIGN_START, sc.CAMPAIGN_END)
    baseline = (date(2026, 8, 16), date(2026, 8, 25))
    source = f"acquisition_source = '{sc.CAMPAIGN_SOURCE}'"
    rest = f"acquisition_source <> '{sc.CAMPAIGN_SOURCE}'"

    lift = _daily_signups(con, source, *campaign) / _daily_signups(con, source, *baseline)
    rest_move = _daily_signups(con, rest, *campaign) / _daily_signups(con, rest, *baseline) - 1

    assert lift >= 2.0
    assert abs(rest_move) < 0.15


def test_tc0007_ground_truth_names_each_planted_scenario(store_path: Path) -> None:
    manifest = json.loads((store_path.parent / "ground_truth.json").read_text())

    found = {(s["id"], s["dimension"], s["segment"], s["direction"]) for s in manifest["scenarios"]}

    assert found == {
        ("funnel_drop", "app_version", "5.4.0", "down"),
        ("retention_decline", "country", "BR", "down"),
        ("campaign_lift", "acquisition_source", "tiktok_ads", "up"),
    }
