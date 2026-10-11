"""The dataset's shape and the three planted scenarios, with their ground truth.

Every number here is a generation parameter. The effect sizes the tests and
evals check are measured from the generated data, never copied from here.
"""

from datetime import date, timedelta
from typing import Final

SEED: Final = 42
USERS: Final = 20_000
DAYS: Final = 60
START: Final = date(2026, 8, 2)
END: Final = START + timedelta(days=DAYS - 1)  # 2026-09-30

OS_MIX: Final = {"Android": 0.6, "iOS": 0.4}
DEVICE_MIX: Final = {"phone": 0.85, "tablet": 0.15}
COUNTRY_MIX: Final = {"US": 0.25, "IN": 0.25, "BR": 0.15, "GB": 0.12, "DE": 0.11, "ID": 0.12}
SOURCE_MIX: Final = {
    "organic": 0.40,
    "google_ads": 0.25,
    "facebook_ads": 0.15,
    "tiktok_ads": 0.10,
    "referral": 0.10,
}

# Releases: (version, first day available). New signups get the latest version;
# existing users upgrade after a random lag.
RELEASES: Final = (("5.2.0", START), ("5.3.0", date(2026, 8, 16)), ("5.4.0", date(2026, 9, 22)))
UPGRADE_LAG_MEAN_DAYS: Final = 4.0

# Activity: probability a user is active d days after signup is
# engagement * BASE_ACTIVE * (d + 1) ** -ACTIVE_DECAY.
BASE_ACTIVE: Final = 0.6
ACTIVE_DECAY: Final = 0.3

# Funnel step probabilities inside one session.
P_SEARCH: Final = 0.35
P_VIEW: Final = 0.8
P_CART: Final = 0.30
P_CHECKOUT: Final = 0.55
P_PURCHASE: Final = 0.62
P_SHARE: Final = 0.05

# Scenario 1: checkout bug in app version 5.4.0 cuts purchase completion.
FUNNEL_DROP_VERSION: Final = "5.4.0"
FUNNEL_DROP_P_PURCHASE: Final = 0.30

# Scenario 2: users in Brazil who sign up from this day return far less often.
RETENTION_COUNTRY: Final = "BR"
RETENTION_FROM: Final = date(2026, 9, 17)
RETENTION_MULTIPLIER: Final = 0.25

# Scenario 3: a TikTok campaign triples TikTok signups in its window.
CAMPAIGN_SOURCE: Final = "tiktok_ads"
CAMPAIGN_START: Final = date(2026, 8, 26)
CAMPAIGN_END: Final = date(2026, 9, 4)
CAMPAIGN_MULTIPLIER: Final = 3.0


def ground_truth() -> dict[str, object]:
    """The manifest evals grade against: what was planted, where and when."""
    return {
        "dataset": {
            "start": START.isoformat(),
            "end": END.isoformat(),
            "users": USERS,
            "seed": SEED,
        },
        "scenarios": [
            {
                "id": "funnel_drop",
                "metric": "conversion",
                "funnel": ["checkout_started", "purchase_completed"],
                "dimension": "app_version",
                "segment": FUNNEL_DROP_VERSION,
                "from": RELEASES[2][1].isoformat(),
                "direction": "down",
            },
            {
                "id": "retention_decline",
                "metric": "retention",
                "day": 7,
                "dimension": "country",
                "segment": RETENTION_COUNTRY,
                "cohorts_from": RETENTION_FROM.isoformat(),
                "direction": "down",
            },
            {
                "id": "campaign_lift",
                "metric": "count",
                "event": "signup",
                "dimension": "acquisition_source",
                "segment": CAMPAIGN_SOURCE,
                "from": CAMPAIGN_START.isoformat(),
                "to": CAMPAIGN_END.isoformat(),
                "direction": "up",
            },
        ],
    }
