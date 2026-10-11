# Klaritics AI Analyst: solution

What the analyst does with a question, which model calls it makes, and what
holds it to the data. Requirements: `docs/product/PRD.md`; decisions:
ADR-0004 (gateway) and ADR-0005 (bounded loop).

## Flow

| Step | Who | Calls | Output |
| --- | --- | --- | --- |
| 1. Intent | model, `intent_parse` | 1, a second only to repair | `IntentDraft`: kind, metric, period, baseline, filters, terms |
| 2. Check | code (`resolve_intent`) | 0 | `Intent` with dates and assumptions, or not tracked, or a repair request |
| 3a. Investigate (why) | model, `investigate` | up to 7 MCP tool calls | the segment it blames, or none |
| 3b. Validate | code | 0 | accepted, or the reason it is not |
| 3c. Fallback | code | 0 or 1 MCP call | the top `likely_cause` from contributions |
| 3d. Measure (how many) | code | 1 MCP call | the number, series or breakdown |
| 4. Narrate | model, `narrate` | 1 | at most 120 words |
| 5. Check numbers | code | 0 | sentences with unsupported numbers removed; template if none survive |

At most eight tool calls per question, whoever makes them (`ToolRunner`).

## Understanding intent, not keywords

The model reads the catalogue's descriptions and maps the user's words to
events and segment values by meaning ("bought", "orders", "checkout
completions"). Code never matches words. It holds the model to the catalogue:

- an event name not in the catalogue is not tracked, never substituted;
- filter values are matched case-insensitively to real values, and an unknown
  one is sent back to the model with the valid list;
- relative periods are computed in code against the last day of data
  (2026-09-30), so the same question always gets the same dates;
- Day-N retention periods are cohort ranges that end N days before the last day.

Paraphrase evals (M3) prove the same intent comes back however the question is worded.

## Model routes

All on `anthropic/claude-haiku-4.5` through OpenRouter (`app/llm/routing.py`).

| Feature | Max output tokens | Timeout |
| --- | --- | --- |
| `intent_parse` | 500 | 30 s |
| `investigate` | 400 | 30 s |
| `narrate` | 400 | 30 s |

No route may exceed 600 (checked at import). Price: USD 1 per million input
tokens, USD 5 per million output tokens; OpenRouter's reported cost wins when present.

## Spend and replay

- Ledger: one JSON line per call (`LLM_LEDGER_PATH`), read back on start.
- Limit: a call whose worst case (prompt at 3 characters per token, every
  output token used) would pass `LLM_BUDGET_USD` (8) is refused before sending.
- `LLM_MODE=record` saves each answer under `LLM_RECORDINGS_DIR/<feature>/<hash>.json`;
  `replay` serves them and fails with the hash when one is missing. The hash
  covers model, prompt, messages, tools and token cap, so a changed prompt
  needs a new recording rather than reusing a stale one.
- Retries: one, on timeouts, 429 and 5xx. A 4xx is never retried.
- Kill switch: `LLM_KILL_<FEATURE>=1` refuses that feature before sending.

## Accepting the model's conclusion

The model's conclusion is accepted only if a `compare_segments` call for exactly
the intent's metric, periods and filters is in the log, and:

- a named cause is marked `likely_cause` there; or
- no cause named, and none is marked there.

Anything else (no drill-down, a cause the evidence does not mark, a missed
cause, no `finish`, the budget spent, the model down) runs the fallback, and
the answer says so (`concluded_by`, `fallback_reason`).

## Number guardrail

Evidence is the pack the narrator saw: every number in it, plus differences,
ratios and relative changes between them. A narrative number is supported
when an evidence number rounds to it at the precision written (as a fraction
or as a percentage). Dates, versions and Day-N labels are names, not
quantities. Small counting words (0 to 10) need no evidence. The template
narrative is built from the same pack and passes the same check.

## Known limits

- Sign is carried by words and not checked ("rose" against a fall).
- One cause per answer; two simultaneous causes name the stronger.
- "Last week" means the latest seven days with data, stated in every answer.
