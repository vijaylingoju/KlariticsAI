"""Generate the seeded event store.

Deterministic for a given seed: the same seed writes the same rows. Users are
generated first (signup day, attributes, engagement), then each user's days,
sessions and funnel events. Rows stream to CSV and load into DuckDB with COPY.
"""

import csv
import json
import math
import random
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from app.analytics.store import DatasetInfo, create_indexes, create_schema, write_meta
from app.seed import scenarios as sc

EventRow = tuple[int, str, str, str, str, str, str, str, str]


@dataclass(frozen=True)
class User:
    """One seeded user and the attributes every event of theirs carries."""

    user_id: str
    signup: datetime
    os: str
    country: str
    device: str
    source: str
    engagement: float
    upgrade_lags: tuple[int, ...]


@dataclass(frozen=True)
class SeedResult:
    """What a seeding run wrote."""

    path: Path
    users: int
    events: int


def _pick(rng: random.Random, mix: dict[str, float]) -> str:
    return rng.choices(list(mix), weights=list(mix.values()), k=1)[0]


def _signup_slots() -> tuple[list[tuple[int, str]], list[float]]:
    """Every (day offset, source) pair and its weight, with the campaign applied."""
    slots: list[tuple[int, str]] = []
    weights: list[float] = []
    for day in range(sc.DAYS):
        current = sc.START + timedelta(days=day)
        in_campaign = sc.CAMPAIGN_START <= current <= sc.CAMPAIGN_END
        for source, share in sc.SOURCE_MIX.items():
            weight = share
            if in_campaign and source == sc.CAMPAIGN_SOURCE:
                weight *= sc.CAMPAIGN_MULTIPLIER
            slots.append((day, source))
            weights.append(weight)
    return slots, weights


def generate_users(rng: random.Random, count: int = sc.USERS) -> list[User]:
    """Draw exactly `count` users, ordered by signup time."""
    slots, weights = _signup_slots()
    picks = rng.choices(slots, weights=weights, k=count)
    drafts: list[tuple[datetime, str]] = []
    for day, source in picks:
        moment = datetime.combine(sc.START + timedelta(days=day), datetime.min.time())
        drafts.append((moment + timedelta(seconds=rng.randrange(86_400)), source))
    drafts.sort()
    users: list[User] = []
    for index, (signup, source) in enumerate(drafts, start=1):
        lags = tuple(int(rng.expovariate(1 / sc.UPGRADE_LAG_MEAN_DAYS)) for _ in sc.RELEASES)
        users.append(
            User(
                user_id=f"u{index:05d}",
                signup=signup,
                os=_pick(rng, sc.OS_MIX),
                country=_pick(rng, sc.COUNTRY_MIX),
                device=_pick(rng, sc.DEVICE_MIX),
                source=source,
                engagement=rng.uniform(0.5, 1.5),
                upgrade_lags=lags,
            )
        )
    return users


def app_version_on(user: User, day: date) -> str:
    """The version the user runs on `day`: the latest release they have upgraded to."""
    signup_day = user.signup.date()
    version = sc.RELEASES[0][0]
    for (name, released), lag in zip(sc.RELEASES, user.upgrade_lags, strict=True):
        available_from = released if released > signup_day else signup_day
        # Users who sign up after a release install it directly; others upgrade after a lag.
        upgrade_day = available_from if released <= signup_day else released + timedelta(days=lag)
        if day >= upgrade_day:
            version = name
    return version


def active_probability(user: User, days_since_signup: int) -> float:
    """Chance the user opens the app on a given later day, with the retention scenario."""
    base = user.engagement * sc.BASE_ACTIVE * math.pow(days_since_signup + 1, -sc.ACTIVE_DECAY)
    if user.country == sc.RETENTION_COUNTRY and user.signup.date() >= sc.RETENTION_FROM:
        base *= sc.RETENTION_MULTIPLIER
    return min(base, 0.95)


def _session_events(
    rng: random.Random, start: datetime, version: str
) -> list[tuple[str, datetime]]:
    """One session's events in time order, with the funnel-drop scenario."""
    events = [("session_start", start)]
    clock = start

    def step(name: str) -> None:
        nonlocal clock
        clock += timedelta(seconds=rng.randrange(20, 240))
        events.append((name, clock))

    if rng.random() < sc.P_SEARCH:
        step("search_performed")
    if rng.random() < sc.P_VIEW:
        for _ in range(rng.randint(1, 4)):
            step("product_viewed")
        if rng.random() < sc.P_SHARE:
            step("share_clicked")
        if rng.random() < sc.P_CART:
            step("add_to_cart")
            if rng.random() < sc.P_CHECKOUT:
                step("checkout_started")
                p_purchase = (
                    sc.FUNNEL_DROP_P_PURCHASE
                    if version == sc.FUNNEL_DROP_VERSION
                    else sc.P_PURCHASE
                )
                if rng.random() < p_purchase:
                    step("purchase_completed")
    return events


def generate_events(rng: random.Random, users: list[User]) -> Iterator[EventRow]:
    """Every event of every user, in user order then time order."""
    event_id = 0
    for user in users:
        signup_day = user.signup.date()
        attrs = (user.os, user.country, user.device, user.source)
        for offset in range((sc.END - signup_day).days + 1):
            day = signup_day + timedelta(days=offset)
            if offset == 0:
                starts = [user.signup]
            else:
                if rng.random() >= active_probability(user, offset):
                    continue
                midnight = datetime.combine(day, datetime.min.time())
                count = 2 if rng.random() < 0.3 else 1
                starts = sorted(
                    midnight + timedelta(seconds=rng.randrange(80_000)) for _ in range(count)
                )
            version = app_version_on(user, day)
            day_events: list[tuple[str, datetime]] = []
            if offset == 0:
                day_events.append(("signup", user.signup))
            for start in starts:
                day_events.extend(_session_events(rng, start, version))
            for name, moment in day_events:
                if moment.date() > sc.END:
                    continue
                event_id += 1
                yield (event_id, user.user_id, name, moment.isoformat(sep=" "), version, *attrs)


def seed(path: Path, seed_value: int = sc.SEED, users: int = sc.USERS) -> SeedResult:
    """Write a fresh store at `path` (replacing any file there) and its ground truth."""
    rng = random.Random(seed_value)  # noqa: S311 - reproducible synthetic data, not security
    people = generate_users(rng, users)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        users_csv = Path(tmp) / "users.csv"
        events_csv = Path(tmp) / "events.csv"
        with users_csv.open("w", newline="") as fh:
            writer = csv.writer(fh)
            for u in people:
                writer.writerow(
                    [
                        u.user_id,
                        u.signup.isoformat(sep=" "),
                        u.os,
                        u.country,
                        u.device,
                        u.source,
                        app_version_on(u, u.signup.date()),
                    ]
                )
        events = 0
        with events_csv.open("w", newline="") as fh:
            writer = csv.writer(fh)
            for row in generate_events(rng, people):
                writer.writerow(row)
                events += 1
        con = duckdb.connect(str(path))
        try:
            create_schema(con)
            con.execute("COPY users FROM ? (FORMAT csv, HEADER false)", [str(users_csv)])
            con.execute("COPY events FROM ? (FORMAT csv, HEADER false)", [str(events_csv)])
            create_indexes(con)
            write_meta(con, DatasetInfo(start=sc.START, end=sc.END, seed=seed_value))
        finally:
            con.close()
    truth_path = path.with_name("ground_truth.json")
    truth_path.write_text(json.dumps(sc.ground_truth(), indent=2) + "\n")
    return SeedResult(path=path, users=len(people), events=events)
