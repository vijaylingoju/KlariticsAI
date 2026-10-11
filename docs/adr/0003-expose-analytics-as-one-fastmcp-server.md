# ADR-0003: Expose analytics as one FastMCP server with stdio and HTTP transports

- Status: Proposed
- Date: 2026-10-11
- Task: KAI-1
- Deciders: Vijay (to accept)

## Context

The brief asks for a reusable MCP server with five capabilities. Bearing's `mcp-server` skill asks for one server per bounded context, both transports, annotations on every tool, structured errors and a protocol test per tool.

## Options considered

### Option A: One server `klaritics-analytics` on the official MCP Python SDK (FastMCP)
Five read-only tools over one DuckDB store. The agent connects to it in-process through the same tool functions, and external clients over stdio or streamable HTTP.

### Option B: Messages API MCP connector with a hosted server
Not applicable: model calls go through OpenRouter, not the Anthropic API.

## Decision

We will build one FastMCP server, `klaritics-analytics`, with five read-only tools, stdio for local hosts and streamable HTTP with a bearer token for services. Tool logic lives in `app/analytics/` so the agent, the API and the server share it. SDK v2 renamed FastMCP to `MCPServer` (`mcp.server.mcpserver`); the decision is unchanged.

## Consequences

- The same functions back the MCP tools and the deterministic fallback, so numbers agree.
- All tools are `read` tier; there is nothing to approve.
- Revisit when a write tool is ever proposed (out of scope today).
