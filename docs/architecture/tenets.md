# System design tenets: KlariticsAI

Rules this team holds itself to on this project. Each is here because
somebody could plausibly do the opposite, and a reviewer can point at a
breach.

## 1. One door to the model

**Every model call goes through `Gateway.complete` in `app/llm/gateway.py`; no other module imports `httpx` to reach a provider or builds a chat-completions body.**

The USD 8 cap, the 600-token cap, the ledger and replay in CI all live in
the gateway (ADR-0004, REQ-022 to REQ-027). A call that skips it is unmetered,
uncapped and breaks keyless CI. TC-0108 scans the source for this.

_A breach looks like:_ an MR adds a "quick summary" helper in `app/reports/` that posts to `openrouter.ai` with its own client.

## 2. Data only through the MCP tools

**The analyst reads data only as an MCP client (`mcp.Client` against the server); `app/agent/` never imports `AnalyticsService` or runs SQL.**

ADR-0003 makes the five tools the one contract, so the agent, the fallback,
re-runs and outside MCP hosts see the same numbers, and a saved tool log can
be replayed exactly (REQ-019).

_A breach looks like:_ an MR adds `service.funnel(...)` inside `app/agent/investigate.py` to save a round trip.

## 3. Code decides, the model proposes

**A model output changes behaviour only after code validates it: intents are resolved against the catalogue, a named cause must be marked `likely_cause` in a matching `compare_segments` result, and anything else runs the deterministic plan.**

The brief forbids unsupported claims (REQ-012, REQ-013, ADR-0005). The model
is good at reading questions and bad at being the source of truth.

_A breach looks like:_ an MR returns `finding.cause` straight from the model's `finish` arguments when validation fails "because the model is usually right".

## 4. Every number is evidence

**Every narrative passes `check_narrative` against the evidence pack the narrator saw, and the template fallback passes the same check; no answer path writes a number that skipped it.**

Unsupported numbers are the failure the PRD names first (B2, REQ-014).

_A breach looks like:_ an MR appends "Revenue impact: about 12%" to `Answer.narrative` after the check, in `app/agent/analyst.py`.

## 5. The bound is counted in one place

**Tool calls are counted only by `ToolRunner` (8 per question) and model output only by the route caps (600 max); callers never keep their own counters or raise the limits.**

REQ-011 and REQ-024 hold whoever calls; the fallback depends on a reserved call.

_A breach looks like:_ an MR constructs `ToolRunner(client, limit=12)` for "complex questions".

## 6. The event store is read-only at runtime

**Runtime code opens the store only through `connect_read_only`; only the seeder writes it, and nothing else is stored in that file.**

ADR-0002 rests on a static, read-only store; tools are annotated read-only.

_A breach looks like:_ an MR stores saved reports as a new table in `data/klaritics.duckdb`.

## 7. CI never calls a model

**Tests and `make eval` run with `LLM_MODE=replay`; a missing recording fails with its hash, and only a person with a key records.**

REQ-027 and B4. A live call in CI spends budget and makes results unrepeatable.

_A breach looks like:_ an MR sets `OPENROUTER_API_KEY` as a CI secret and runs `make eval-record` in a workflow.

## 8. Untrusted text is escaped where it is rendered

**Question, model and data text reach HTML only through `html.escape`, and JSON inside `<script>` has `</` escaped.**

Questions are free text and the model can be steered (threat model T-07).

_A breach looks like:_ an MR renders `answer.narrative` in `app/reports/render.py` with a Markdown-to-HTML library and no escaping.
