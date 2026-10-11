# Architecture decisions: KlariticsAI

One row per decision, and every contradiction settled once so it is not
settled again, differently, in each file that runs into it.

## Decisions

| Id | Title | Area | Status | Reversibility |
| --- | --- | --- | --- | --- |
| ADR-0001 | Use the Bearing python-api stack | backend language | Proposed | awkward: every module, test and gate would move |
| ADR-0002 | Use DuckDB for the seeded event store | analytics store | Proposed | cheap: the store is rebuilt by the seeder and SQL lives in one service |
| ADR-0003 | Expose analytics as one FastMCP server | api style | Proposed | awkward: the agent, re-runs and outside hosts all speak MCP |
| ADR-0004 | Route model calls through an OpenRouter gateway | llm provider and models | Proposed | cheap: one provider class behind the gateway |
| ADR-0005 | Run the agent as an intent-first bounded workflow loop | llm provider and models | Proposed | awkward: intent, investigate and fallback would be rewritten |
| ADR-0006 | Publish from cloud sessions through the GitHub connector | ci and delivery | Proposed | cheap: a process rule, no runtime code |

## Conflicts that were settled

### Where saved reports are stored

**Between:** ADR-0002 (Consequences: "Reports are stored in a separate DuckDB file"), `app/reports/store.py` (one JSON file per report), US-06-002.

**Decision.** Proposed: keep JSON files, the code as built, and correct ADR-0002's consequence before it is accepted.

**Why.** Reports are written once and read whole; JSON files need no schema and keep the event store untouched (tenet 6).

**Settled by:** open (Vijay)

**What now has to change to match:**
- ADR-0002 Consequences: replace the DuckDB report file with JSON files under `REPORTS_DIR` (the ADR is Proposed, so it can be edited before acceptance).

### Whether the USD 8 limit holds across processes

**Between:** REQ-026, AC-US-03-002-1, `Dockerfile` (`WEB_CONCURRENCY=2`), `app/llm/ledger.py` (in-memory total per process).

**Decision.** Proposed: run the API with one worker until the ledger re-reads the file under a lock before each check.

**Why.** Each worker counts only its own calls after start-up, so two workers can spend up to USD 16 minus the start-up total (HLD section 8).

**Settled by:** open (Vijay)

**What now has to change to match:**
- `Dockerfile` or `docker-compose.yml`: `WEB_CONCURRENCY=1`, or a new story for a cross-process ledger.

### Whether the eval runs in CI

**Between:** AC-US-07-001-1 ("run on replay in CI"), `.github/workflows/ci.yml` (no eval job), `evals/recordings/` (absent).

**Decision.** Proposed: record once with an OpenRouter session, commit the recordings, then add the `eval` job, as `docs/genai/evals.md` already plans.

**Why.** A replay job with no recordings fails on every case.

**Settled by:** open (Vijay)

**What now has to change to match:**
- `.github/workflows/ci.yml`: an `eval` job running `make eval`, after recordings land.

### Who may call the analyst API

**Between:** ADR-0003 (bearer token on the MCP HTTP transport), `app/api/analyst/router.py` (no auth on `/v1`), REQ-026.

**Decision.** Proposed: a new ADR for analyst API authentication and per-caller limits before the API is reachable by anyone but the owner.

**Why.** The MCP server is protected and the API that wraps the same data and spends the model budget is not.

**Settled by:** open (Vijay)

**What now has to change to match:**
- New ADR: authentication and per-caller limits for the analyst API.
