# Architecture: KlariticsAI

- Task: KAI-4
- Serves: REQ-001 to REQ-027, US-02-006, US-03-001, US-04-002, US-06-002, ADR-0002, ADR-0003, ADR-0004, ADR-0005
- Generated from the code on 2026-10-11 by architecture-diagram
- Sources: compose `docker-compose.yml`, k8s none, packages `app/`, image `Dockerfile`
- Drawn: [System architecture](diagrams/KlariticsAI_SystemArchitecture_v1.svg) ([PNG](diagrams/KlariticsAI_SystemArchitecture_v1.png)), [Architecture flow](diagrams/KlariticsAI_ArchitectureFlow_v1.svg) ([PNG](diagrams/KlariticsAI_ArchitectureFlow_v1.png)), rendered from [architecture.json](architecture.json)

There are no Kubernetes or Helm manifests, so the container view is drawn from
`docker-compose.yml` and the `Dockerfile`. That is the only deployment the
repository describes; the CI `deploy` job is a stub that exits 1
(`.github/workflows/ci.yml`).

## 1. Context

```mermaid
C4Context
  title System context: KlariticsAI
  Person(pm, "Product manager or analyst", "Asks why a metric moved, reads and re-runs reports")
  Person(dev, "Developer or MCP host", "Calls the five analytics tools directly")
  System(sys, "KlariticsAI", "AI analyst and MCP analytics server over a seeded event store")
  System_Ext(or, "OpenRouter", "Claude Haiku 4.5 chat completions")
  System_Ext(cdn, "jsDelivr CDN", "vega, vega-lite and vega-embed scripts for HTML reports")
  Rel(pm, sys, "Questions and reports", "HTTP/JSON, /v1")
  Rel(dev, sys, "Tool calls", "MCP over stdio or streamable HTTP")
  Rel(sys, or, "Chat completions", "HTTPS/JSON")
  Rel(pm, cdn, "Browser loads chart scripts", "HTTPS")
```

## 2. Containers

```mermaid
C4Container
  title Containers: KlariticsAI (docker-compose.yml)
  Person(pm, "Product manager or analyst")
  Person(dev, "MCP host")
  System_Boundary(b, "KlariticsAI") {
    Container(api, "api", "FastAPI, gunicorn with 2 uvicorn workers", "Analyst, reports, health. Runs the MCP server in-process")
    Container(mcp, "mcp", "MCP SDK MCPServer, streamable HTTP :8090", "Five read-only analytics tools behind a bearer token")
    ContainerDb(duck, "event store", "DuckDB file baked into the image", "users, events, meta. Read-only at runtime")
    ContainerDb(state, "analyst-data volume", "JSONL and JSON files", "Spend ledger and saved reports")
  }
  System_Ext(or, "OpenRouter", "Claude Haiku 4.5")
  Rel(pm, api, "Asks, saves, fetches, re-runs", "HTTP/JSON, no auth")
  Rel(dev, mcp, "Calls tools", "HTTP, Authorization Bearer")
  Rel(api, duck, "Reads", "DuckDB read_only")
  Rel(mcp, duck, "Reads", "DuckDB read_only")
  Rel(api, state, "Appends spend, writes reports", "file IO")
  Rel(api, or, "Chat completions", "HTTPS, LLM_MODE live or record")
```

Each container has its own copy of the event store: the image seeds it at build
time (`Dockerfile` line `RUN .venv/bin/python -m app.seed`), so the two copies
are identical by seed, not shared.

## 3. Components: api

Packages under 30 lines are skipped: `app/domain/` (empty `__init__.py`).

```mermaid
C4Component
  title Components: api container
  Container_Boundary(c, "api") {
    Component(apir, "app/api", "package", "Routes /v1/questions, /v1/reports, /healthz, /readyz")
    Component(agent, "app/agent", "package", "Analyst.ask: intent, investigation, narrative, charts")
    Component(guard, "app/guardrails", "package", "Number check on the narrative")
    Component(llm, "app/llm", "package", "Gateway: routes, budget ledger, providers, replay")
    Component(srv, "app/mcp_server", "package", "MCPServer with five tools, run in-process")
    Component(an, "app/analytics", "package", "AnalyticsService: SQL over DuckDB")
    Component(rep, "app/reports", "package", "Report store, Markdown and HTML render, re-run")
    Component(core, "app/core", "package", "Settings, logging, request id, errors, tracing")
  }
  ContainerDb(duck, "event store", "DuckDB", "")
  ContainerDb(files, "ledger and reports", "files", "")
  System_Ext(or, "OpenRouter", "")
  Rel(apir, agent, "Calls Analyst.ask")
  Rel(apir, rep, "Saves, renders, re-runs")
  Rel(agent, srv, "MCP Client calls")
  Rel(agent, llm, "Gateway.complete")
  Rel(agent, guard, "check_narrative")
  Rel(srv, an, "Calls service methods")
  Rel(rep, srv, "Re-runs tool calls")
  Rel(an, duck, "SQL, read-only")
  Rel(llm, or, "HTTPS")
  Rel(llm, files, "Ledger append")
  Rel(rep, files, "JSON files")
```

## 4. Sequences

### Ask a why-question (POST /v1/questions, US-04-002, US-04-003)

Participants are the functions in `app/api/analyst/router.py`,
`app/agent/analyst.py`, `app/agent/intent.py`, `app/agent/investigate.py`,
`app/agent/narrative.py` and `app/llm/gateway.py`.

```mermaid
sequenceDiagram
  autonumber
  actor U as Caller
  participant R as router.ask
  participant A as Analyst.ask
  participant I as intent.parse_intent
  participant V as investigate.investigate
  participant T as ToolRunner.call
  participant N as narrative.narrate
  participant G as Gateway.complete
  participant O as OpenRouter
  U->>R: POST /v1/questions (question, save)
  alt body invalid (length outside 3 to 500, extra field)
    R-->>U: 422 validation_error envelope
  end
  alt store not loaded at startup
    R-->>U: 503 service_unavailable envelope
  end
  R->>A: ask(question)
  A->>I: parse_intent (at most 2 model calls)
  I->>G: complete(intent_parse)
  G->>G: kill switch, worst-case budget check
  alt feature disabled or over budget
    G-->>I: FeatureDisabledError or BudgetExceededError, nothing sent
  end
  G->>O: POST chat completions
  alt timeout, 429 or 5xx twice
    O-->>G: failure
    G-->>A: ProviderUnavailableError
    A-->>R: Answer kind unavailable
    R-->>U: 200 with kind unavailable
  end
  alt intent invalid after one repair
    A-->>U: 200 with kind clarify
  end
  alt untracked event or not answerable
    A-->>U: 200 with kind not_tracked or not_answerable, no number
  end
  A->>V: investigate(intent)
  V->>G: complete(investigate) with tools, up to 9 rounds
  V->>T: up to 7 agent tool calls
  alt model fails, stops, budget spent or conclusion not backed by evidence
    V->>T: fallback compare_segments (8th call at most), or reuse a matching one
  end
  A->>N: narrate(pack)
  N->>G: complete(narrate)
  alt model unavailable or fewer than 5 words survive the number check
    N-->>A: template narrative
  end
  A-->>R: Answer with narrative, charts, table, tool log, cost
  opt save is true
    R->>R: ReportStore.save, atomic rename
  end
  R-->>U: 200 Answer
```

The ledger write happens after the provider replies (`Gateway.complete` in
`app/llm/gateway.py`). A crash between the reply and the append loses that
call's spend from the ledger; OpenRouter has already billed it.

### Re-run a saved report (POST /v1/reports/{id}/rerun, US-06-002)

```mermaid
sequenceDiagram
  autonumber
  actor U as Caller
  participant R as router.rerun_report
  participant S as ReportStore.get
  participant X as rerun.rerun
  participant M as MCPServer (in-process)
  U->>R: POST /v1/reports/{id}/rerun
  alt store not loaded
    R-->>U: 503 service_unavailable envelope
  end
  R->>S: get(id)
  alt id not 16 hex characters or file missing
    S-->>R: ReportNotFoundError
    R-->>U: 404 not_found envelope
  end
  R->>X: rerun(answer, target)
  loop every logged tool call
    X->>M: call_tool(tool, arguments)
  end
  X-->>R: RerunResult (reproduced, differences)
  R-->>U: 200 RerunResult
```

## 5. Legend

| Style | Meaning |
| --- | --- |
| Solid edge | Call found in code or config (sources table) |
| Dotted edge (SVG) | Bulk write: the seeder builds the store once |
| Skipped | `app/domain/` (empty), tests, evals harness |
| Not drawn | `make mcp` stdio server: a local process started by an MCP host, same code as the `mcp` container |

## 6. Sources

| Element | File | Line |
| --- | --- | --- |
| api container | docker-compose.yml | 5 |
| mcp container | docker-compose.yml | 21 |
| gunicorn, 2 workers (WEB_CONCURRENCY) | Dockerfile | 19 |
| seeder at image build | Dockerfile | 13 |
| api -> event store, read-only | app/main.py | 48 |
| read-only connection | app/analytics/store.py | 93 |
| mcp -> event store | app/mcp_server/__main__.py | 28 |
| mcp bearer token | app/mcp_server/__main__.py | 37 |
| api -> OpenRouter | app/llm/providers.py | 33 |
| api -> ledger | app/llm/ledger.py | 73 |
| api -> reports | app/reports/store.py | 45 |
| api -> recordings | app/llm/providers.py | 167 |
| browser -> jsDelivr | app/reports/render.py | 13 |
| agent -> MCP in-process | app/agent/analyst.py | 170 |

## 7. Unconfirmed

- None. Every edge has a call site or a config line above. The OpenRouter key's
  own spend limit named in ADR-0004 is account configuration and is not drawn.
