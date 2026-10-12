# Threat model: Klaritics AI Analyst

- Task: KAI-4
- Serves: US-02-006, US-03-001, US-03-002, US-04-001, US-05-001, US-06-002, REQ-022, REQ-026, REQ-034, ADR-0002, ADR-0003, ADR-0004
- HLD: [docs/design/HLD.md](../design/HLD.md); diagram: [docs/architecture/klariticsai-c4.md](../architecture/klariticsai-c4.md)
- Sensitive classes: auth, external input
- Author: unattributed, 2026-10-11, status: Draft (written after the code; mitigations cite the code at `feature/KAI-3-M3Evals`)

Scope: the `api` and `mcp` containers in `docker-compose.yml`, the `make ask`
CLI, and their calls to OpenRouter and jsDelivr. The dataset is synthetic
with no personal data, so the assets are the model budget, the API key, the
MCP token, the integrity of answers, saved reports and availability.

Abuse-path pass: not run (the `security-threat-model` skill is not installed in this session).

## 1. Assets

| Asset | Where it lives | Owner | Why an attacker wants it |
| --- | --- | --- | --- |
| OpenRouter API key | `OPENROUTER_API_KEY` in `.env` or the compose environment | owner (Vijay) | Spend on someone else's account, up to the key's own limit |
| Model budget (USD 8) | Spend ledger JSONL, `LLM_LEDGER_PATH` | owner | Exhausting it denies every user an analysis |
| MCP bearer token | `MCP_HTTP_TOKEN` in `.env` | owner | Query the analytics tools as a trusted host |
| Answer integrity | `Answer` returned by `/v1/questions` and saved reports | owner | Make a product decision rest on a false cause or number |
| Saved reports | JSON files under `REPORTS_DIR` on the `analyst-data` volume | owner | Read other analysts' questions and findings |
| Event store | DuckDB file in each image | owner | Alter numbers every answer rests on |
| Availability of the API | `api` container, 2 workers | owner | Deny the service |

## 2. Trust boundaries

| # | From | To | Protocol | Auth on the edge | Source |
| --- | --- | --- | --- | --- | --- |
| B1 | caller (any network that reaches the port) | api | HTTP, port 8080 | none | docker-compose.yml:7 |
| B2 | MCP host | mcp | HTTP, port 8090, streamable HTTP | shared bearer token | docker-compose.yml:24 |
| B3 | api | OpenRouter | HTTPS | bearer API key | app/llm/providers.py:143 |
| B4 | report reader's browser | jsDelivr | HTTPS | none, no integrity hash | app/reports/render.py:13 |
| B5 | api, mcp | DuckDB event store | file, read-only | file permissions, user `app` | app/analytics/store.py:93 |
| B6 | api | ledger and reports volume | file | file permissions | docker-compose.yml:16 |
| B7 | model output | analyst code | in-process data | none: untrusted input | app/agent/investigate.py:108 |

## 3. Entry points

| # | Entry point | Kind | Auth required | Boundary |
| --- | --- | --- | --- | --- |
| E1 | `POST /v1/questions` | route | none | B1 |
| E2 | `GET /v1/reports` | route | none | B1 |
| E3 | `GET /v1/reports/{id}`, `/markdown`, `/html` | route | none | B1 |
| E4 | `POST /v1/reports/{id}/rerun` | route | none | B1 |
| E5 | `GET /healthz`, `GET /readyz` | route | none | B1 |
| E6 | MCP streamable HTTP `/mcp` | route | bearer token | B2 |
| E7 | MCP stdio (`make mcp`) | local process | the launching user | none |
| E8 | `make ask` CLI | local process | the launching user | B3 |
| E9 | OpenRouter completion bodies | callback data | none: parsed as untrusted | B3, B7 |
| E10 | HTML report page in a browser | rendered output | none | B4 |

## 4. Threats (STRIDE)

| Id | Entry or boundary | Category | Threat | Likelihood | Impact | Mitigation | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-01 | E1 | Spoofing | Anyone who reaches port 8080 asks questions as if they were an analyst | H | M | new story: authenticate callers of the analyst API | unmitigated |
| T-02 | E1, B7 | Tampering | Prompt injection in the question makes the model name a cause the data does not support | M | H | conclusion accepted only when compare_segments marks it likely_cause, app/agent/investigate.py:108 | mitigated |
| T-03 | E1, B7 | Tampering | Prompt injection makes the intent use an invented event or filter value | M | M | names and values checked against the catalogue, app/agent/intent.py:197 | mitigated |
| T-04 | E1, B7 | Tampering | Prompt injection makes the narrator state a number the tools never returned | M | H | sentences with unsupported numbers removed, app/guardrails/numbers.py:116 | mitigated |
| T-05 | E1, B7 | Tampering | Prompt injection steers narrative words with no number in them (a wrong segment named in prose, advice) | M | M | new story: check named segments and events in the narrative against the evidence | unmitigated |
| T-06 | E1, B7 | Denial of service | Injected question drives the agent into many tool calls | M | L | at most 8 tool calls per question, app/agent/tools.py:55 | mitigated |
| T-07 | E1 | Denial of service | Repeated questions exhaust the USD 8 budget, then every user gets unavailable | H | H | new story: per-caller rate limit and budget share on the analyst API | unmitigated |
| T-08 | E1 | Denial of service | Each of the 2 workers keeps its own spend total, so the cap is up to USD 16 | M | M | new story: one cross-process spend ledger, or one worker | planned |
| T-09 | E1 | Denial of service | A worst-case call is refused before sending once spend plus its worst case passes the limit | L | M | worst-case budget check before sending, app/llm/ledger.py:58 | mitigated |
| T-10 | E1 | Denial of service | Slow provider holds a question for minutes with no overall deadline | M | M | new story: deadline per question on the analyst API | planned |
| T-11 | E1 | Denial of service | Oversized question inflates prompt cost | L | L | question limited to 500 characters, app/api/analyst/router.py:27 | mitigated |
| T-12 | E1 | Repudiation | No caller identity in logs, so spend and reports cannot be tied to a person | M | L | new story: authenticate callers of the analyst API | unmitigated |
| T-13 | E2, E3 | Information disclosure | Any caller lists and reads every saved report | H | M | new story: report ownership per caller | unmitigated |
| T-14 | E3, E4 | Tampering | Path traversal through the report id reads or writes outside REPORTS_DIR | M | H | id must match 16 hex characters, app/reports/store.py:41 | mitigated |
| T-15 | E10 | Tampering | Script in a question, model output or data value runs in the report page (XSS) | M | H | every value escaped, app/reports/render.py:122 | mitigated |
| T-16 | E10 | Tampering | A string closes the chart script block from inside the JSON specs | L | H | escape of the closing tag sequence in embedded JSON, app/reports/render.py:137 | mitigated |
| T-17 | B4, E10 | Tampering | Compromised CDN file runs script in every report page | L | H | new story: subresource integrity or self-hosted chart scripts for HTML reports | planned |
| T-18 | E4 | Denial of service | Re-runs repeat up to 8 queries per call with no limit, loading DuckDB | L | L | new story: per-caller rate limit and budget share on the analyst API | planned |
| T-19 | E5 | Information disclosure | Readiness failure reveals internals | L | L | readiness returns only the failed check name, app/api/health/router.py:52 | mitigated |
| T-20 | E1, E3 | Information disclosure | An unhandled error leaks a traceback to the caller | L | M | 500 envelope with no detail, app/core/errors.py:114 | mitigated |
| T-21 | E6 | Spoofing | Caller without the token calls the MCP tools | M | M | constant-time bearer check, 401 on mismatch, app/mcp_server/auth.py:21 | mitigated |
| T-22 | E6 | Spoofing | MCP HTTP starts with no token configured | L | H | refuses to start without MCP_HTTP_TOKEN, app/mcp_server/__main__.py:33 | mitigated |
| T-23 | E6, B2 | Information disclosure | Token sniffed on plain HTTP between the host and port 8090 | M | M | new story: TLS in front of the MCP HTTP transport | planned |
| T-24 | E6 | Elevation of privilege | One shared token: a leaked token cannot be revoked for one client alone | M | L | new story: per-client MCP tokens | planned |
| T-25 | E6, E7 | Tampering | SQL injection through tool arguments | M | H | values bound as parameters, columns from a fixed list, app/analytics/service.py:157 | mitigated |
| T-26 | E6, E7 | Tampering | Filter values outside the data probe the store or error out | L | L | every filter value checked against the data, app/analytics/service.py:135 | mitigated |
| T-27 | E6, E7 | Elevation of privilege | A tool writes to the event store | L | H | store opened read-only, app/analytics/store.py:93 | mitigated |
| T-28 | E6 | Denial of service | Heavy compare_segments calls in a loop from an MCP host | M | L | new story: rate limit on the MCP HTTP transport | planned |
| T-29 | B3, E8 | Information disclosure | OpenRouter key written to logs | L | H | key held as SecretStr, app/core/config.py:37 | mitigated |
| T-30 | B3 | Information disclosure | Key or prompt text written to the ledger or log line | L | H | log line carries tokens and cost only, app/llm/gateway.py:116 | mitigated |
| T-31 | B3 | Information disclosure | Key saved into a committed recording | L | H | recording stores the request body without headers, app/llm/providers.py:203 | mitigated |
| T-32 | B3 | Spoofing | A leaked key spends outside this service, past the ledger | M | H | new story: confirm and document the spend limit on the OpenRouter key | planned |
| T-33 | E9 | Tampering | Malformed tool-call arguments from the model crash the agent | M | L | arguments parsed defensively, invalid JSON kept as data, app/llm/providers.py:96 | mitigated |
| T-34 | E9 | Denial of service | Model never calls finish and loops | M | L | budget of 7 tool calls, then fallback, app/agent/investigate.py:166 | mitigated |
| T-35 | E7, E8 | Spoofing | considered, none: local processes run as the user who launched them, with that user's own key and files | | | | |
| T-36 | E5 | Elevation of privilege | considered, none: health routes are read-only and take no input | | | | |

## 5. Residual risks

| Threat | Risk accepted or planned | Owner (role) | Revisit |
| --- | --- | --- | --- |
| T-01 | open: no auth on the analyst API; acceptable only while it runs on the owner's machine | service owner | 2026-10-25 |
| T-05 | open: prose without numbers is not checked | service owner | 2026-10-25 |
| T-07 | open: one caller can spend the whole budget | service owner | 2026-10-25 |
| T-08 | planned: decisions conflict 2 | service owner | 2026-10-18 |
| T-10 | planned: no per-question deadline | service owner | 2026-10-25 |
| T-12 | open: follows T-01 | service owner | 2026-10-25 |
| T-13 | open: follows T-01 | service owner | 2026-10-25 |
| T-17 | planned: CDN scripts without integrity hashes | service owner | 2026-11-01 |
| T-18 | planned: follows T-07 | service owner | 2026-10-25 |
| T-23 | planned: TLS terminator before any non-local MCP host | service owner | 2026-11-01 |
| T-24 | planned: per-client tokens | service owner | 2026-11-01 |
| T-28 | planned: MCP rate limit | service owner | 2026-11-01 |
| T-32 | planned: confirm the OpenRouter key limit (ADR-0004, HLD A-03) | service owner | 2026-10-18 |

## 6. New stories needed

- Authenticate callers of the analyst API (mitigates T-01, T-12), acceptance: `/v1/*` returns 401 without a valid credential. Needs an ADR first.
- Per-caller rate limit and budget share on the analyst API (mitigates T-07, T-18), acceptance: one caller over its limit gets 429 while another still gets answers.
- One cross-process spend ledger, or one worker (mitigates T-08), acceptance: two processes on one ledger file never pass USD 8 together.
- Deadline per question on the analyst API (mitigates T-10), acceptance: a provider that never answers yields a reply within the deadline.
- Check named segments and events in the narrative against the evidence (mitigates T-05), acceptance: a narrative naming a segment the evidence does not mark loses that sentence.
- Report ownership per caller (mitigates T-13), acceptance: caller A gets 404 for caller B's report id and does not see it listed.
- Subresource integrity or self-hosted chart scripts for HTML reports (mitigates T-17), acceptance: each script tag carries an integrity hash or a same-origin URL.
- TLS in front of the MCP HTTP transport (mitigates T-23), acceptance: plain HTTP to the MCP port is refused outside localhost.
- Per-client MCP tokens (mitigates T-24), acceptance: revoking one token leaves other clients working.
- Rate limit on the MCP HTTP transport (mitigates T-28), acceptance: a client over its limit gets 429.
- Confirm and document the spend limit on the OpenRouter key (mitigates T-32), acceptance: the runbook names the limit and where it is set.

## 7. Counts

Assets 7, boundaries 7, entry points 10, threats 34 plus 2 considered, none
(mitigated 21, planned 8, unmitigated 5). Gate: passed.
