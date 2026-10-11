# Bearing feedback from the Klaritics AI Analyst build

What this build needed that Bearing v0.7.0 did not give, and a suggestion for
each. Ordered by how much time the gap cost.

| # | Gap | What happened here | Suggestion |
| --- | --- | --- | --- |
| 1 | Pushing from a cloud or background session | The pre-push hook refuses any push when an agent is running, so work done while the owner is away cannot reach a branch. ADR-0006 | A `PUSH_CONFIRM=task-branches` mode: agents may push `feature/*` and open draft PRs; protected branches, force pushes and merges stay blocked |
| 2 | No cumulative spend cap in `llm-gateway` | The brief requires a hard USD 8 limit; the gateway template has per-tenant rate limits only | A ledger with a pre-call worst-case check, persisted across restarts (`app/llm/ledger.py` here) |
| 3 | OpenRouter is named but not implemented | Template covers Anthropic's SDK only | An OpenAI-compatible provider template with OpenRouter's `usage.cost` |
| 4 | Record and replay keyed by request | The template's `FakeProvider` replays fixtures but has no record mode wired to the gateway | `LLM_MODE=live|record|replay` with a request hash covering every input that shapes the answer |
| 5 | `llm-agent` assumes Anthropic's tool runner | A bounded loop with a validated conclusion and a deterministic fallback had to be written from scratch | A "bounded investigator" template: budget, reserve call, evidence validation, fallback |
| 6 | No numeric grounding guardrail | `llm-guardrails` covers PII and injection, not "every number must come from tool output" | A number-check guardrail: evidence set with derived values, rounding-aware matching, sentence removal |
| 7 | No synthetic data skill | Planted scenarios with ground truth had to be designed and tuned by hand (two scenario fixes after tests exposed them) | A `synthetic-data` skill: deterministic seed, planted effects, ground-truth manifest, tests that check the plant from plain SQL |
| 8 | No report or chart skill | Vega-Lite specs, Markdown and HTML rendering written by hand | A `reports` skill with escaping rules and a re-run check |
| 9 | `llm-eval` minimum is 20 trajectories and CI needs a key | Replay makes CI keyless; the skill assumes live calls | Document replay-based CI gates; allow a perfect-reader check as the always-on pipeline test |
| 10 | MCP SDK v2 changes | `FastMCP` became `MCPServer`; errors are prefixed by the SDK unless a tool returns `CallToolResult` | Update `mcp-server` templates for SDK v2 |
| 11 | Scaffold assumes Postgres | `brg-scaffold --databases DuckDB` still wrote Postgres, Alembic and an integration job | Honour `--databases` in the Makefile, CI and compose |
| 12 | Stage order is opt-in | Only `autopilot` (`bin/brg-autopilot`) enforces the stages and their gates. A build that runs the skills one by one, as this one did, can skip HLD, LLD, threat model and event sheet while `make check` and CI stay green | A `make stages` target (or a `brg-autopilot status --check` step in the CI template) that fails a merge request when a stage its scope requires has no document on disk |
| 13 | Cloud sessions fail on the scaffolded sandbox | `.claude/settings.json` sets `sandbox.failIfUnavailable: true`; cloud images lack `bubblewrap` and `socat`, so a fresh session refuses to start | Document the setup-script line `apt-get install -y bubblewrap socat` in `new-repo`, or detect the cloud image in `doctor` |
