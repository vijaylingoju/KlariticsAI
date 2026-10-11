"""The tracked event catalogue and the segment dimensions.

One source of truth for the seeder, the tools and the agent. An event or a
dimension that is not listed here is not tracked.
"""

from typing import Final, Literal

Dimension = Literal["app_version", "os", "country", "device", "acquisition_source"]

DIMENSIONS: Final[tuple[Dimension, ...]] = (
    "app_version",
    "os",
    "country",
    "device",
    "acquisition_source",
)

DIMENSION_DESCRIPTIONS: Final[dict[Dimension, str]] = {
    "app_version": "Version of the mobile app that sent the event, e.g. 5.4.0",
    "os": "Operating system: Android or iOS",
    "country": "ISO country code of the user, e.g. BR for Brazil",
    "device": "Device class: phone or tablet",
    "acquisition_source": "Channel the user signed up from, e.g. organic or tiktok_ads",
}

EVENTS: Final[dict[str, str]] = {
    "signup": "User created an account. The start event for retention cohorts.",
    "session_start": "User opened the app. Counts as being active that day.",
    "search_performed": "User ran a product search.",
    "product_viewed": "User opened a product detail page.",
    "add_to_cart": "User added a product to the cart.",
    "checkout_started": "User began checkout from the cart.",
    "purchase_completed": "User paid and the order was placed. Also called an order or a purchase.",
    "share_clicked": "User shared a product with someone.",
}

# The funnel most questions about "conversion" or "checkout" mean.
PURCHASE_FUNNEL: Final[tuple[str, ...]] = (
    "product_viewed",
    "add_to_cart",
    "checkout_started",
    "purchase_completed",
)
