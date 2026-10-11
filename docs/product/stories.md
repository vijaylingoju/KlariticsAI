# Stories

Epics, stories and acceptance criteria derived from `docs/product/PRD.md`.
Milestones: M1 (data and tools), M2 (the analyst), M3 (evals and ship).

## EP-01 Seeded dataset (M1)

### US-01-001 Seed a realistic event dataset
Why it matters: B1, B2. Covers REQ-001, REQ-028.
As a developer, I need a deterministic seeded dataset so every analysis and eval is reproducible.

- AC-US-01-001-1: Given seed 42, when the seeder runs, then the database holds exactly 20,000 users and events spanning 60 consecutive days.
- AC-US-01-001-2: Given the same seed run twice, then both databases hold identical row counts and identical per-day event counts.
- AC-US-01-001-3: Every user carries app version, OS, country, device and acquisition source; every event carries a user id, an event name in the catalogue and a timestamp inside the 60 days.

### US-01-002 Plant three scenarios with ground truth
Why it matters: B1. Covers REQ-029, REQ-030, REQ-031.

- AC-US-01-002-1: Funnel drop: checkout-to-purchase conversion for the planted app version after its release date is at least 15 percentage points below the other versions in the same period; the other versions stay within 3 points of their rate before the release.
- AC-US-01-002-2: Retention decline: Day-7 retention for the planted country's cohorts from 2026-09-17 to 2026-09-23 (the latest week with an observable Day 7) is at least 10 points below its cohorts of the week before; other countries together move by less than 3 points.
- AC-US-01-002-3: Campaign lift: daily signups from the planted acquisition source during the campaign window are at least 2 times its baseline; other sources move by less than 15%.
- AC-US-01-002-4: The seeder writes `ground_truth.json` naming each scenario's metric, segment, window and expected direction.

## EP-02 MCP analytics server (M1)

### US-02-001 List tracked events
Covers REQ-006, REQ-020.
- AC-US-02-001-1: `list_events` returns every event name with its description and total count.
- AC-US-02-001-2: Every other tool, given an event not in the catalogue, returns a `not_tracked` error naming the event and the closest tracked names.

### US-02-002 Count events
Covers REQ-002.
- AC-US-02-002-1: `count_events` returns totals for a date range, optionally per day or per week, optionally filtered by any segment dimension, and optionally grouped by one dimension.
- AC-US-02-002-2: Counts equal a direct SQL count over the same rows (unique users and total events both available).

### US-02-003 Funnel analysis
Covers REQ-003.
- AC-US-02-003-1: `funnel` returns users entering each step in order, with step and overall conversion, within a conversion window.
- AC-US-02-003-2: Step counts never increase from one step to the next.

### US-02-004 Retention analysis
Covers REQ-004.
- AC-US-02-004-1: `retention` returns Day-N retention for users whose start event falls in a cohort range, optionally filtered and grouped by a dimension.
- AC-US-02-004-2: Retention is between 0 and 1, and the cohort size is reported with it.

### US-02-005 Segment comparison
Covers REQ-005, REQ-010, REQ-012, REQ-017.
- AC-US-02-005-1: `compare_segments` compares a metric (event count, conversion or retention) between a current and a baseline period for every value of a dimension.
- AC-US-02-005-2: Each segment row carries baseline, current, change, and its contribution to the total change, split into rate and mix effects; contributions sum to the total change within rounding.

### US-02-006 Tools are safe for a model
Covers REQ-034.
- AC-US-02-006-1: Every tool is read-only, annotated, validates input past the schema (dates inside the data, known dimensions, bounded group sizes), and returns typed errors with `code`, `message`, `retryable`.
- AC-US-02-006-2: The server runs on stdio and streamable HTTP; a protocol test calls every tool.

## EP-03 LLM gateway (M2)

### US-03-001 One gateway for every model call
Covers REQ-022, REQ-023, REQ-024, REQ-025.
- AC-US-03-001-1: All model calls go through `complete()`; a call-site check finds none outside `app/llm/`.
- AC-US-03-001-2: Calls use `anthropic/claude-haiku-4.5` with `max_tokens` never above 600.
- AC-US-03-001-3: Each call records input, output tokens and USD cost in a persisted ledger.

### US-03-002 Spend limit
Covers REQ-026.
- AC-US-03-002-1: A call whose worst-case cost would push the ledger past USD 8 is refused before sending, with a typed `BudgetExceeded` error.

### US-03-003 Record and replay
Covers REQ-027.
- AC-US-03-003-1: In replay mode the gateway serves recorded responses by request hash and makes no network call; a missing recording fails the test with the hash.

## EP-04 Analyst agent (M2)

### US-04-001 Understand intent
Covers REQ-007, REQ-008.
- AC-US-04-001-1: A question is parsed into a validated Intent (type, metric, events, filters, periods, dimensions).
- AC-US-04-001-2: Paraphrases without the key words resolve to the same Intent as the original question.
- AC-US-04-001-3: Relative periods resolve against the dataset end date.

### US-04-002 Bounded investigation
Covers REQ-009, REQ-010, REQ-011.
- AC-US-04-002-1: The agent never makes more than eight tool calls per question.
- AC-US-04-002-2: The agent drills into at least one dimension before naming a cause.

### US-04-003 Deterministic fallback
Covers REQ-012.
- AC-US-04-003-1: When the bound is hit, no cause is named, or validation fails, the deterministic plan runs and returns a cause from contributions.

## EP-05 Evidence guardrails (M2)

### US-05-001 Validate numbers
Covers REQ-013, REQ-014.
- AC-US-05-001-1: Every number in the narrative is matched to tool evidence (values, differences, ratios, percentage-point changes) within rounding tolerance.
- AC-US-05-001-2: A sentence with an unmatched number is removed and counted.

### US-05-002 Untracked events
Covers REQ-020.
- AC-US-05-002-1: A question about an untracked event answers that the event is not tracked and names no number for it.

## EP-06 Reports (M2)

### US-06-001 Answer shape
Covers REQ-015, REQ-016, REQ-017, REQ-018.
- AC-US-06-001-1: The answer holds a narrative of at most 120 words, at least one chart spec, a contribution table, and the full tool-call log.

### US-06-002 Save and reproduce
Covers REQ-019, REQ-021.
- AC-US-06-002-1: A validated answer can be saved and fetched by id as JSON, Markdown and HTML.
- AC-US-06-002-2: Re-running a saved report's tool log reproduces the same numbers.

## EP-07 Evaluation (M3)

### US-07-001 Eval suite
Covers REQ-032, REQ-033, REQ-035.
- AC-US-07-001-1: 15 questions plus 2 paraphrases each run on replay in CI.
- AC-US-07-001-2: The report scores root-cause accuracy, numeric accuracy, tool calls used and fallback rate.

## Coverage

| REQ | Stories |
| --- | --- |
| REQ-001 | US-01-001 |
| REQ-002 | US-02-002 |
| REQ-003 | US-02-003 |
| REQ-004 | US-02-004 |
| REQ-005 | US-02-005 |
| REQ-006 | US-02-001 |
| REQ-007 | US-04-001 |
| REQ-008 | US-04-001 |
| REQ-009 | US-04-002 |
| REQ-010 | US-04-002, US-02-005 |
| REQ-011 | US-04-002 |
| REQ-012 | US-04-003, US-02-005 |
| REQ-013 | US-05-001 |
| REQ-014 | US-05-001 |
| REQ-015 | US-06-001 |
| REQ-016 | US-06-001 |
| REQ-017 | US-06-001, US-02-005 |
| REQ-018 | US-06-001 |
| REQ-019 | US-06-002 |
| REQ-020 | US-02-001, US-05-002 |
| REQ-021 | US-06-002 |
| REQ-022 | US-03-001 |
| REQ-023 | US-03-001 |
| REQ-024 | US-03-001 |
| REQ-025 | US-03-001 |
| REQ-026 | US-03-002 |
| REQ-027 | US-03-003 |
| REQ-028 | US-01-001 |
| REQ-029 | US-01-002 |
| REQ-030 | US-01-002 |
| REQ-031 | US-01-002 |
| REQ-032 | US-07-001 |
| REQ-033 | US-07-001 |
| REQ-034 | US-02-006 |
| REQ-035 | US-07-001 |

35 of 35 requirements covered.
