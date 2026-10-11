# Event design sheet

Every product analytics event, designed before it is emitted. Code emits
exactly this list. No PII in properties.

Scope: the synthetic mobile-shop events the seeder writes into the DuckDB
event store (`app/seed/generator.py`), which the analyst and the MCP tools
analyse. The KlariticsAI service itself emits no product events. Source of
truth in code: `EVENTS` and `DIMENSIONS` in `app/analytics/catalog.py`; the
journey is derived from the code (no product journey document exists for
the synthetic app), so every row is marked derived.

Every event carries the standard properties below; the Properties column
lists only what an event adds, and none adds anything today.

| Event name | When it fires | Properties (name: type) | Platform | Owner | Added in |
| --- | --- | --- | --- | --- | --- |
| `signup` | once per user, at the signup moment; that day's only session starts at the same timestamp (derived) | standard only | seeded mobile app (Android, iOS) | Vijay | KAI-1 |
| `session_start` | each session start: one at signup, then on each later active day one session, or two with probability 0.3 (derived) | standard only | seeded mobile app | Vijay | KAI-1 |
| `search_performed` | in a session with probability 0.35, 20 to 240 s after the previous event (derived) | standard only | seeded mobile app | Vijay | KAI-1 |
| `product_viewed` | in a session with probability 0.8, 1 to 4 times (derived) | standard only | seeded mobile app | Vijay | KAI-1 |
| `share_clicked` | after product views, probability 0.05 (derived) | standard only | seeded mobile app | Vijay | KAI-1 |
| `add_to_cart` | after product views, probability 0.30 (derived) | standard only | seeded mobile app | Vijay | KAI-1 |
| `checkout_started` | after `add_to_cart`, probability 0.55 (derived) | standard only | seeded mobile app | Vijay | KAI-1 |
| `purchase_completed` | after `checkout_started`, probability 0.62, or 0.30 on app version 5.4.0 (planted funnel drop) (derived) | standard only | seeded mobile app | Vijay | KAI-1 |

### Standard properties (columns of `events`, `app/analytics/store.py`)

| Property | Type | Values | Source |
| --- | --- | --- | --- |
| `event_id` | bigint | 1, 2, ... in generation order | seeder counter |
| `user_id` | string | `u00001` to `u20000` | synthetic account id, `generate_users` |
| `event_name` | string | the eight names above | `_session_events`, `generate_events` |
| `ts` | timestamp (UTC, no zone) | 2026-08-02 to 2026-09-30 | seeder clock |
| `app_version` | enum | `5.2.0`, `5.3.0`, `5.4.0` | `app_version_on`: latest release the user has upgraded to that day |
| `os` | enum | `Android`, `iOS` | user attribute, fixed per user |
| `country` | enum (ISO code) | `US`, `IN`, `BR`, `GB`, `DE`, `ID` | user attribute, fixed per user |
| `device` | enum | `phone`, `tablet` | user attribute, fixed per user |
| `acquisition_source` | enum | `organic`, `google_ads`, `facebook_ads`, `tiktok_ads`, `referral` | user attribute, fixed per user |

The `users` table repeats the four fixed attributes with `signup_ts` and
`signup_app_version`.

### Questions each event answers

| Event | The analyst's question, in one line |
| --- | --- |
| `signup` | How many users signed up per day, by acquisition source (planted TikTok campaign lift, 2026-08-26 to 2026-09-04)? |
| `session_start` | What share of a signup cohort came back on Day N, by country (planted BR decline from 2026-09-17)? |
| `search_performed` | How many users searched per week? |
| `product_viewed` | First step of the purchase funnel: how many users viewed a product? |
| `share_clicked` | How often are products shared, by device? |
| `add_to_cart` | What share of viewers add to cart? |
| `checkout_started` | What share of carts reach checkout? |
| `purchase_completed` | What share of checkouts complete, by app version (planted 5.4.0 drop from 2026-09-22)? |

Purchase funnel (`PURCHASE_FUNNEL`): `product_viewed` > `add_to_cart` >
`checkout_started` > `purchase_completed`, steps within `window_hours`
(default 24) of the first.

### Paths to each outcome

`purchase_completed` and `signup` have one path each: the seeder's generator.
There are no webhooks, retries or manual actions to reconcile, and an event
generated after 2026-09-30 is dropped, never moved.

### Audit (2026-10-11, from reading the code)

8 in sheet, 8 distinct names emitted by production code (the seeder), 8 in both:
`signup`, `session_start`, `search_performed`, `product_viewed`,
`share_clicked`, `add_to_cart`, `checkout_started`, `purchase_completed`.
`app/analytics/catalog.py` lists the same 8. Mismatches with the rules,
each a decision for the owner, Proposed: keep as is:

- `signup`, `session_start` and `add_to_cart` are not `object_verb` past tense (`user_signed_up`, `session_started`, `product_added_to_cart` would be). Renaming changes the catalogue, the seeder, the tests and every recording hash.
- `purchase_completed` carries no order id, amount or currency, so revenue questions cannot be answered.
- No `session_id`: funnels join on user and time window, not on session.

## Naming

`object_verb` in snake_case, past tense: `invoice_paid`, `search_submitted`.
Properties in snake_case. Enumerations listed in the property column.
Three seeded names predate this rule (see the audit); new events follow it.

## Identity

User: `user_id`, a synthetic account id (`u` and five digits) assigned in
signup order by `generate_users` in `app/seed/generator.py`; never an email.
Session: none recorded. Device: none recorded; `device` is a class (phone or
tablet), not an id. Details in [tracking-plan.md](tracking-plan.md).
