# Test cases

Every acceptance criterion in `docs/product/stories.md` maps to the tests that
prove it. A test's name starts with its id (`test_tc0050_...`), so
`pytest -k tc0050` runs it.

Stores: **full** is the seeded store (20,000 users, 60 days, seed 42), built
once and cached under `.cache/`; **tiny** is the hand-written store in
`tests/conftest.py`, small enough to check every number by hand.

## M1: data and tools

| TC | Proves | Store | File | Criterion |
| --- | --- | --- | --- | --- |
| TC-0001 | 20,000 users, events over exactly 60 days | full | `tests/seed/test_seed.py` | AC-US-01-001-1 |
| TC-0002 | Every event has all five dimensions, a catalogue name and a known user | full | `tests/seed/test_seed.py` | AC-US-01-001-3 |
| TC-0003 | The same seed gives identical per-day, per-event counts | generated | `tests/seed/test_seed.py` | AC-US-01-001-2 |
| TC-0004 | 5.4.0 converts at least 15 points below other versions; others stay within 3 | full, plain SQL | `tests/seed/test_seed.py` | AC-US-01-002-1 |
| TC-0005 | BR Day-7 falls at least 10 points week on week; other countries move under 3 | full, plain SQL | `tests/seed/test_seed.py` | AC-US-01-002-2 |
| TC-0006 | tiktok_ads daily signups at least double in the campaign; others move under 15% | full, plain SQL | `tests/seed/test_seed.py` | AC-US-01-002-3 |
| TC-0007 | `ground_truth.json` names each scenario's dimension, segment and direction | full | `tests/seed/test_seed.py` | AC-US-01-002-4 |
| TC-0010 | `list_events` returns events, counts, dimensions and the range | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-001-1 |
| TC-0011 | Every capability reports an untracked event as `not_tracked`, with closest names | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-001-2 |
| TC-0012 | Counts of events and unique users match hand counts | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-002-2 |
| TC-0013 | Daily series fill empty days; weekly series start on Monday | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-002-1 |
| TC-0014 | Group by and filters | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-002-1 |
| TC-0015 | Group by with a series is refused | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-006-1 |
| TC-0016 | Dates outside the data or reversed are refused | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-006-1 |
| TC-0017 | An unknown filter value lists the valid values | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-006-1 |
| TC-0018 | Every error serialises with `code`, `message`, `retryable` | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-006-1 |
| TC-0020 | Funnel counts ordered steps inside the window; a longer window admits later steps | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-003-1 |
| TC-0021 | Funnel step counts never increase (property, random ranges) | full | `tests/analytics/test_scenarios.py` | AC-US-02-003-2 |
| TC-0022 | Funnel segments split the entering users | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-003-1 |
| TC-0030 | Day-N retention by hand, overall and per segment | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-004-1 |
| TC-0031 | A cohort too recent for Day N is refused with the latest valid end | tiny | `tests/analytics/test_capabilities.py` | AC-US-02-004-1 |
| TC-0032 | Retention is between 0 and 1 and never exceeds eligible users (property) | full | `tests/analytics/test_scenarios.py` | AC-US-02-004-2 |
| TC-0040 | Rate contributions sum to the total change (property) | none | `tests/analytics/test_contributions.py` | AC-US-02-005-2 |
| TC-0041 | Count contributions sum to the total change (property) | none | `tests/analytics/test_contributions.py` | AC-US-02-005-2 |
| TC-0042 | A new segment contributes through mix only | none | `tests/analytics/test_contributions.py` | AC-US-02-005-2 |
| TC-0043 | A cause outranks bystanders; a healthy complement is not a cause | none | `tests/analytics/test_contributions.py` | AC-US-04-003-1 |
| TC-0044 | Uniform growth names no cause | none | `tests/analytics/test_contributions.py` | AC-US-04-003-1 |
| TC-0045 | One source tripling is the cause of a lift | none | `tests/analytics/test_contributions.py` | AC-US-04-003-1 |
| TC-0050 | Purchase conversion drop is attributed to app_version 5.4.0 alone | full | `tests/analytics/test_scenarios.py` | AC-US-02-005-1, AC-US-04-003-1 |
| TC-0051 | Last week's Day-7 drop is attributed to country BR alone | full | `tests/analytics/test_scenarios.py` | AC-US-02-005-1, AC-US-04-003-1 |
| TC-0052 | The brief's Android Day-7 question is attributed to BR | full | `tests/analytics/test_scenarios.py` | AC-US-02-005-1 |
| TC-0053 | The signup lift is attributed to tiktok_ads alone | full | `tests/analytics/test_scenarios.py` | AC-US-02-005-1, AC-US-04-003-1 |
| TC-0054 | A quiet period names no cause | full | `tests/analytics/test_scenarios.py` | AC-US-04-003-1 |
| TC-0055 | Contributions in every dimension sum to the change on real data | full | `tests/analytics/test_scenarios.py` | AC-US-02-005-2 |
| TC-0060 | Five tools listed, each read-only, annotated, described, with an output schema | tiny, MCP | `tests/mcp/test_server.py` | AC-US-02-006-1 |
| TC-0061 | Every tool answers a valid call with structured content | tiny, MCP | `tests/mcp/test_server.py` | AC-US-02-006-2 |
| TC-0062 | An untracked event returns a `not_tracked` tool error as JSON | tiny, MCP | `tests/mcp/test_server.py` | AC-US-02-001-2 |
| TC-0063 | Dates outside the data return a typed error with the dataset range | tiny, MCP | `tests/mcp/test_server.py` | AC-US-02-006-1 |
| TC-0064 | Arguments the schema forbids are rejected | tiny, MCP | `tests/mcp/test_server.py` | AC-US-02-006-1 |
| TC-0065 | Tool output equals the service's numbers | tiny, MCP | `tests/mcp/test_server.py` | AC-US-02-002-2 |
| TC-0066 | HTTP refuses a missing or wrong bearer token | tiny, HTTP | `tests/mcp/test_server.py` | AC-US-02-006-2 |
| TC-0067 | The stdio server, launched as a process, serves the tools | tiny, stdio | `tests/mcp/test_server.py` | AC-US-02-006-2 |

## M2: the analyst

**scripted** is a model stand-in that plays a fixed script per feature (`tests/agent/conftest.py`); it
exercises every path the code takes, while what the real model says is graded in the M3 evals.

| TC | Proves | Store | File | Criterion |
| --- | --- | --- | --- | --- |
| TC-0100 | Every route uses Haiku 4.5 and never asks for more than 600 output tokens | fake | `tests/llm/test_gateway.py` | AC-US-03-001-2 |
| TC-0101 | Cost is priced from usage, or taken from OpenRouter when it reports one | fake | `tests/llm/test_gateway.py` | AC-US-03-001-3 |
| TC-0102 | The ledger persists spend across restarts; replayed calls cost nothing | fake | `tests/llm/test_gateway.py` | AC-US-03-001-3 |
| TC-0103 | A call whose worst case passes the limit is refused before sending | fake | `tests/llm/test_gateway.py` | AC-US-03-002-1 |
| TC-0104 | Replay serves by request hash, never the network; a missing or changed request fails with its hash | replay | `tests/llm/test_gateway.py` | AC-US-03-003-1 |
| TC-0105 | One retry on a transient failure, after the wait the provider asks for (capped at 60 s); none on a rejected request | fake | `tests/llm/test_gateway.py` | AC-US-03-001-1 |
| TC-0106 | A disabled feature is refused before sending | fake | `tests/llm/test_gateway.py` | AC-US-03-001-1 |
| TC-0107 | OpenRouter request shape, tool-call parsing and status mapping (a model's invalid tool call is retryable) | in-memory HTTP | `tests/llm/test_gateway.py` | AC-US-03-001-1, AC-US-03-001-2 |
| TC-0108 | No model call anywhere outside `app/llm/` | source scan | `tests/llm/test_gateway.py` | AC-US-03-001-1 |
| TC-0109 | Logs carry tokens and cost, never prompt or answer text | fake | `tests/llm/test_gateway.py` | AC-US-03-001-3 |
| TC-0110 | LLM_MODEL and LLM_BASE_URL switch every route to another OpenAI-compatible model; an unpriced model is refused; a local server needs no key; OpenRouter-only fields go only to OpenRouter | in-memory HTTP | `tests/llm/test_gateway.py` | AC-US-03-001-1, AC-US-03-002-1 |
| TC-0200 | Relative periods resolve against the last day of data | none | `tests/agent/test_periods.py` | AC-US-04-001-3 |
| TC-0201 | Day-N cohort periods end where Day N is observable | none | `tests/agent/test_periods.py` | AC-US-04-001-3 |
| TC-0202 | The default baseline is the equal-length range before | none | `tests/agent/test_periods.py` | AC-US-04-001-3 |
| TC-0203 | Periods outside the data or incomplete are refused | none | `tests/agent/test_periods.py` | AC-US-04-001-1 |
| TC-0210 | A why-question resolves to a metric, dates and stated assumptions | full | `tests/agent/test_intent.py` | AC-US-04-001-1 |
| TC-0211 | Retention last week uses observable cohorts; filter case is fixed | full | `tests/agent/test_intent.py` | AC-US-04-001-1, AC-US-04-001-3 |
| TC-0212 | A baseline the user names is kept | full | `tests/agent/test_intent.py` | AC-US-04-001-1 |
| TC-0213 | An untracked term, or an event the model invents, makes the question not tracked | full | `tests/agent/test_intent.py` | AC-US-05-002-1 |
| TC-0214 | Unknown events and filter values are problems naming the valid values | full | `tests/agent/test_intent.py` | AC-US-04-001-1 |
| TC-0215 | A mixed question answers the tracked part and lists the untracked | full | `tests/agent/test_intent.py` | AC-US-05-002-1 |
| TC-0216 | The intent tool schema is self-contained; the prompt lists the whole catalogue | full | `tests/agent/test_intent.py` | AC-US-04-001-2 |
| TC-0217 | One invalid intent is repaired with the problems; two give up; model failure surfaces | scripted | `tests/agent/test_intent.py` | AC-US-04-001-1 |
| TC-0220 | A conclusion backed by compare_segments evidence is accepted | full, scripted | `tests/agent/test_investigate.py` | AC-US-04-002-2 |
| TC-0221 | The agent may drill further before finishing | full, scripted | `tests/agent/test_investigate.py` | AC-US-04-002-2 |
| TC-0222 | No drill-down, an unbacked or missed cause, or no finish falls back to contributions | full, scripted | `tests/agent/test_investigate.py` | AC-US-04-003-1 |
| TC-0223 | Tool calls never exceed eight; the last is the fallback's | full, scripted | `tests/agent/test_investigate.py` | AC-US-04-002-1, AC-US-04-003-1 |
| TC-0224 | The model down falls back with one call | full, scripted | `tests/agent/test_investigate.py` | AC-US-04-003-1 |
| TC-0225 | The fallback reuses a matching comparison instead of calling again | full, scripted | `tests/agent/test_investigate.py` | AC-US-04-002-1 |
| TC-0226 | No cause is accepted when the evidence marks none | full, scripted | `tests/agent/test_investigate.py` | AC-US-04-002-2 |
| TC-0227 | Tool errors are logged and returned to the model | full, scripted | `tests/agent/test_investigate.py` | AC-US-06-001-1 |
| TC-0230 | An explanation has a narrative, charts, the contribution table, the tool log and its cost | full, scripted | `tests/agent/test_analyst.py` | AC-US-06-001-1 |
| TC-0231 | A narrative sentence with an unsupported number is removed and counted | full, scripted | `tests/agent/test_analyst.py` | AC-US-05-001-2 |
| TC-0232 | The narrative is at most 120 words | full, scripted | `tests/agent/test_analyst.py` | AC-US-06-001-1 |
| TC-0233 | The template answers when the narrator is down, and passes the number check | full, scripted | `tests/agent/test_analyst.py` | AC-US-04-003-1, AC-US-05-001-1 |
| TC-0234 | An untracked event is answered as not tracked with no number | full, scripted | `tests/agent/test_analyst.py` | AC-US-05-002-1 |
| TC-0235 | A measure question makes one planned call and charts it | full, scripted | `tests/agent/test_analyst.py` | AC-US-06-001-1 |
| TC-0236 | The brief's Android Day-7 question names BR (via the fallback) | full, scripted | `tests/agent/test_analyst.py` | AC-US-04-003-1 |
| TC-0237 | An unparseable question asks to rephrase and runs nothing | full, scripted | `tests/agent/test_analyst.py` | AC-US-04-001-1 |
| TC-0238 | The model down runs no analysis | full, scripted | `tests/agent/test_analyst.py` | AC-US-03-001-1 |
| TC-0239 | Funnel, retention and breakdown answers chart and keep their numbers | full, scripted | `tests/agent/test_analyst.py` | AC-US-06-001-1, AC-US-05-001-1 |
| TC-0300 | Rates as percentages, points, raw changes, counts, relative changes and ratios are supported | none | `tests/guardrails/test_numbers.py` | AC-US-05-001-1 |
| TC-0301 | A sentence with an unsupported number is removed | none | `tests/guardrails/test_numbers.py` | AC-US-05-001-2 |
| TC-0302 | Dates, versions, Day-N labels and small counting words are not checked | none | `tests/guardrails/test_numbers.py` | AC-US-05-001-1 |
| TC-0303 | Word limits cut at whole sentences | none | `tests/guardrails/test_numbers.py` | AC-US-06-001-1 |
| TC-0304 | Any rate written as a percentage is supported (property) | none | `tests/guardrails/test_numbers.py` | AC-US-05-001-1 |
| TC-0400 | A saved report reads back identical and is listed | full, scripted | `tests/reports/test_reports.py` | AC-US-06-002-1 |
| TC-0401 | Unknown or malformed report ids, path traversal included, are not found | none | `tests/reports/test_reports.py` | AC-US-06-002-1 |
| TC-0402 | Markdown holds the narrative, assumptions, table, charts and tool log | full, scripted | `tests/reports/test_reports.py` | AC-US-06-002-1 |
| TC-0403 | HTML escapes everything from the question, the model and the data | full, scripted | `tests/reports/test_reports.py` | AC-US-06-002-1 |
| TC-0404 | Re-running a report reproduces every number; a changed number is reported | full, scripted | `tests/reports/test_reports.py` | AC-US-06-002-2 |
| TC-0410 | The API answers, saves and serves a report as JSON, Markdown and HTML | full, scripted, HTTP | `tests/reports/test_reports.py` | AC-US-06-002-1 |
| TC-0411 | The API re-runs a saved report | full, scripted, HTTP | `tests/reports/test_reports.py` | AC-US-06-002-2 |
| TC-0412 | An unsaved answer has no id and is not listed | full, scripted, HTTP | `tests/reports/test_reports.py` | AC-US-06-002-1 |
| TC-0413 | The API rejects invalid questions and client-supplied answers | HTTP | `tests/reports/test_reports.py` | AC-US-06-002-1 |
| TC-0414 | An unknown report is 404 with the error envelope | HTTP | `tests/reports/test_reports.py` | AC-US-06-002-1 |

## M3: evaluation

| TC | Proves | Store | File | Criterion |
| --- | --- | --- | --- | --- |
| TC-0500 | The golden set has 15 questions with 2 paraphrases each, all labelled | none | `tests/evals/test_eval_pipeline.py` | AC-US-07-001-1 |
| TC-0501 | A perfect reader scores every base case on root cause, intent and numbers | full, oracle | `tests/evals/test_eval_pipeline.py` | AC-US-07-001-2 |
| TC-0502 | A perfect reader passes the gate with no fallback | full, oracle | `tests/evals/test_eval_pipeline.py` | AC-US-07-001-2 |
| TC-0503 | An empty answer scores zero on every grader | full | `tests/evals/test_eval_pipeline.py` | AC-US-07-001-2 |
| TC-0504 | The gate fails on errors, low accuracy and too many tool calls | none | `tests/evals/test_eval_pipeline.py` | AC-US-07-001-2 |
| EVAL | Haiku 4.5 on 45 recorded cases: root cause, intent, numbers, paraphrase consistency, fallback rate | full, replay | `make eval` | AC-US-04-001-2, AC-US-07-001-1, AC-US-07-001-2 |
