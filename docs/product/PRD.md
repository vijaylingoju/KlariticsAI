# PRD: Klaritics AI Analyst

Source: `docs/product/source/brief.txt` (task brief plus owner direction)   Normalised: 2026-10-11
Owner: Vijay (vijaylingoju)   Tracker epic: none (BEARING_TRACKER=none, ids prefixed KAI)

## 1. Problem

Product managers and analysts need to investigate why a product metric moved and which
segments caused it, and today that takes manual querying across dimensions (L3, L7).
Answers must be evidence-backed: an unsupported number or an untracked event presented as
fact misleads decisions (L9, L11).

## 2. Business objectives

| Id | Objective | Target (measurable) | Source |
| --- | --- | --- | --- |
| B1 | Analysts get the root cause of a metric change from one natural-language question | Planted cause identified on the eval set; target: unconfirmed (proposed 13 of 15) | L3, L7, L15 |
| B2 | Every number an analyst reads is supported by a tool result | 0 unsupported numbers in final answers on the eval set | L9, L15 |
| B3 | Every analysis can be reproduced and kept | Saved report re-runs to identical numbers | L11 |
| B4 | Model spend stays bounded and CI stays offline | Spend never exceeds USD 8; 0 live LLM calls in CI | L13 |

## 3. Non-goals

- Writing back to Klaritics (L19).
- Path analysis and campaign creation (L19); path analysis and top-properties are stretch goals only (L19).
- Data sources other than the seeded dataset (L19).

## 4. Personas

| Persona | Group | Who they are | What they need | Source |
| --- | --- | --- | --- | --- |
| Product manager | 00 end user | Owns a product area and its metrics | Why a metric changed, in plain language, with evidence | L3 |
| Analyst | 00 end user | Investigates metrics and shares findings | Reproducible analysis, saved reports, exact tool calls | L3, L11 |
| Developer | 03 integration | Builds on the analytics capabilities | A reusable MCP server with the five capabilities | L5, L17 |

## 5. Requirement statements

One testable statement per id. Ids are never reused or renumbered.

| Id | Statement | Persona | Source | Flags |
| --- | --- | --- | --- | --- |
| REQ-001 | The system stores a seeded product event dataset in DuckDB or PostgreSQL. | Developer | L5, L19 | none |
| REQ-002 | The system exposes an event count capability through an MCP server. | Developer | L5 | none |
| REQ-003 | The system exposes a funnel analysis capability through an MCP server. | Developer | L5 | none |
| REQ-004 | The system exposes a retention analysis capability through an MCP server. | Developer | L5 | none |
| REQ-005 | The system exposes a segment comparison capability through an MCP server. | Developer | L5 | none |
| REQ-006 | The system exposes an event listing capability through an MCP server. | Developer | L5 | none |
| REQ-007 | The system accepts analytics questions in natural language. | Product manager | L7 | none |
| REQ-008 | The system interprets a question by its intent, not by keyword matching. | Product manager | L22 | ambiguous: acceptance set in design |
| REQ-009 | The agent selects the analyses a question needs and executes them through the MCP tools. | Product manager | L7 | none |
| REQ-010 | The agent drills down across app version, operating system, country, device and acquisition source to identify the segments responsible for a change. | Analyst | L7 | none |
| REQ-011 | The investigation stops after eight tool calls. | Analyst | L9 | none |
| REQ-012 | When the agent cannot identify the cause within the limit, the system runs a deterministic plan that compares the metric and evaluates contributions across dimensions. | Analyst | L9 | none |
| REQ-013 | The system validates every numerical claim against tool results in code. | Analyst | L9 | none |
| REQ-014 | The system removes unsupported numbers from the answer. | Analyst | L9 | none |
| REQ-015 | The final response includes a concise narrative explaining the findings. | Product manager | L11 | ambiguous: acceptance set in design |
| REQ-016 | The final response includes relevant charts. | Product manager | L11 | ambiguous: acceptance set in design |
| REQ-017 | The final response includes a contribution table of the most influential segments. | Analyst | L11 | none |
| REQ-018 | The final response includes a complete record of the tool calls and their parameters. | Analyst | L11 | none |
| REQ-019 | An analysis can be reproduced from its tool-call record. | Analyst | L11 | none |
| REQ-020 | When a requested event is not tracked, the response states explicitly that it is not tracked. | Analyst | L11 | none |
| REQ-021 | Analysts can save validated answers as reports. | Analyst | L11 | none |
| REQ-022 | Every LLM request goes through one centralized OpenRouter gateway. | Developer | L13 | none |
| REQ-023 | The gateway uses Claude Haiku 4.5. | Developer | L13 | none |
| REQ-024 | The gateway caps every call at 600 output tokens. | Developer | L13 | none |
| REQ-025 | The gateway tracks token usage and cost per call. | Developer | L13 | none |
| REQ-026 | The gateway refuses calls that would exceed a USD 8 spending limit. | Developer | L13 | none |
| REQ-027 | The gateway replays recorded model responses in tests, so CI makes no live LLM calls. | Developer | L13 | none |
| REQ-028 | The seed contains 20,000 users and 60 days of events. | Developer | L15 | none |
| REQ-029 | The seed plants a funnel conversion drop tied to one app version. | Developer | L15 | none |
| REQ-030 | The seed plants a retention decline in one country. | Developer | L15 | none |
| REQ-031 | The seed plants a campaign-driven lift. | Developer | L15 | none |
| REQ-032 | An evaluation suite of 15 questions measures whether the agent identifies the planted causes. | Developer | L15 | none |
| REQ-033 | The evaluation suite measures whether the agent's numerical claims are accurate. | Developer | L15 | none |
| REQ-034 | The system is production ready: configuration, logging, health checks, typed errors and a container image. | Developer | L23 | ambiguous: acceptance set in design |
| REQ-035 | Every requirement is covered by automated tests that run without network access. | Developer | L23, L24 | none |

## 6. Constraints

- Model access only through the capped OpenRouter API (L19); model Claude Haiku 4.5, 600 output tokens per call, USD 8 limit (L13).
- Store: DuckDB or PostgreSQL, run in Docker (L19). Chosen: DuckDB (ADR-0002).
- Data: the seeded dataset only (L19).
- Bearing skills drive the build (owner direction, project memory).

## 7. Glossary

| Term | Meaning |
| --- | --- |
| Intent | The structured reading of a question: question type, metric, events, filters, periods, dimensions |
| Contribution | The share of a metric's change explained by one segment, split into rate and mix effects |
| Tool call | One invocation of an MCP analytics tool with its arguments and result |
| Replay | Serving a recorded model response by request hash instead of calling the model |

## 8. Could not extract

- A numeric acceptance target for root-cause accuracy (B1): proposed 13 of 15, owner to confirm (Q-001).
- Who reads reports and where they are viewed (REQ-021): assumed API plus HTML file (Q-002).
