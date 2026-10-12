# Tracking plan

The rules every event follows. The event sheet lists the events; this
page explains identity, consent, platforms and ownership.

## Destinations

| Destination | Purpose | Owner | Key location (name only) |
| --- | --- | --- | --- |
| DuckDB event store, `events` table (ADR-0002) | funnels, retention, segment comparison through the MCP tools | Vijay | none: a local file at `STORE_PATH` |

No vendor SDK is wired and none is planned (HLD section 6). Events are
written only by the seeder, never sent over a network.

## Identity

- Anonymous id: none; every seeded event belongs to a signed-up user.
- User id: `user_id`, synthetic, `u00001` to `u20000`, set by `generate_users` in `app/seed/generator.py`.
- Tenant id: none; single synthetic product.

## Consent

Not applicable: the data is generated, no person is tracked. Any real
source added later needs this section rewritten before the first event.

## Standard properties (stamped by the context layer, never by callers)

Stamped by `generate_events` in `app/seed/generator.py` on every event:
`app_version` (per user per day), `os`, `country`, `device`,
`acquisition_source` (fixed per user). No `session_id`, `screen`, `locale`
or `consent` property exists.

## Naming

Events `object_verb`, past tense, snake_case. Never rename a shipped event;
add a new one and deprecate the old with a date. `signup`, `session_start`
and `add_to_cart` predate the rule (EVENT_SHEET.md, audit).

## Ownership and change

Vijay owns every event. A new or changed event is a row in the sheet and an
entry in `EVENTS` in `app/analytics/catalog.py` in the same MR as the
seeder change; the seed tests (TC-0001 to TC-0007) and the eval recordings
must be refreshed with it.
