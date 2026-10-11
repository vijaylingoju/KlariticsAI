# KlariticsAI

Klaritics AI Analyst: ask why a product metric moved and get a validated,
evidence-backed answer. Built spec first with the Bearing skills; the product
spec is in `docs/product/` and the decisions in `docs/adr/`.

`make help` lists every command; `make check` is the gate CI runs.

## Run

```
cp .env.example .env
make setup
make seed        # builds data/klaritics.duckdb: 20,000 users, 60 days, seed 42
make dev         # API on http://localhost:8080 (/healthz, /readyz, /docs)
make mcp         # MCP server over stdio
make mcp-http    # MCP server over streamable HTTP on :8090/mcp (bearer MCP_HTTP_TOKEN)
make mcp-dev     # MCP Inspector against the stdio server
make ask Q="Why did purchases drop last week?"   # one answer as Markdown
make up          # both in Docker; the image seeds its own store
```

Model calls need `OPENROUTER_API_KEY` (see `.env.example`). `LLM_MODE=replay`
answers only from recorded responses and never calls the network; tests and CI
run that way.

## Ask the analyst

```
POST /v1/questions            {"question": "...", "save": true}
GET  /v1/reports              saved reports, newest first
GET  /v1/reports/{id}         JSON; /markdown and /html render it
POST /v1/reports/{id}/rerun   re-run the tool calls and check every number reproduces
```

Each answer holds a narrative of at most 120 words, Vega-Lite charts, the
contribution table, the full tool-call log, the assumptions it made (dates,
baseline) and what its model calls cost.

How it works: the model turns the question into a structured intent, mapping
words to events by meaning; code checks it against the catalogue and turns
"last week" into dates. For a "why" question the model investigates with the
MCP tools, at most seven calls with one kept for the fallback; its conclusion
counts only if `compare_segments` evidence backs it, otherwise the
deterministic plan names the cause from contributions. Every number in the
narrative is checked against the evidence and a sentence that fails is
removed. Details: `docs/genai/analyst-solution.md`.

## What is here

| Path | What it does |
| --- | --- |
| `app/seed/` | Deterministic generator and the three planted scenarios (`scenarios.py`, `ground_truth.json`) |
| `app/analytics/` | The event store, the five analytics capabilities, and change attribution (`contributions.py`) |
| `app/mcp_server/` | `klaritics-analytics`: five read-only MCP tools over stdio and HTTP |
| `app/llm/` | The only path to a model: routes, 600-token cap, spend ledger with a USD 8 limit, record and replay |
| `app/agent/` | Intent, period resolution, bounded investigation and fallback, narrative, charts |
| `app/guardrails/` | Number check: every number in a narrative must come from tool evidence |
| `app/reports/` | Saved reports, Markdown and HTML rendering, re-run |
| `app/api/` | FastAPI app; health and readiness against the store |
| `docs/product/` | Brief, PRD (REQ ids), stories with acceptance criteria |
| `docs/testing/test-cases.md` | Every test id mapped to the criterion it proves |

### MCP tools

| Tool | Answers |
| --- | --- |
| `list_events` | Which events are tracked, the dimensions and their values, the date range |
| `count_events` | How many, as a total, a daily or weekly series, or per segment |
| `funnel` | Ordered conversion through 2 to 6 steps within a window |
| `retention` | Day-N retention for a signup cohort |
| `compare_segments` | Why a metric changed: contribution, `explained` and `separation_z` per segment, likely causes first |

Every tool is read-only and annotated. Errors come back as JSON with `code`
(for example `not_tracked`), `message`, `retryable` and `details`.

## Planted scenarios

| Scenario | Metric | Cause |
| --- | --- | --- |
| Funnel drop | Checkout to purchase falls from 2026-09-22 | app_version 5.4.0 |
| Retention decline | Day-7 retention falls for cohorts from 2026-09-17 | country BR |
| Campaign lift | Signups rise 2026-08-26 to 2026-09-04 | acquisition_source tiktok_ads |
