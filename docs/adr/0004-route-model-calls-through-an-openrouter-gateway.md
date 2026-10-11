# ADR-0004: Route every model call through an OpenRouter gateway with a spend ledger and replay

- Status: Proposed
- Date: 2026-10-11
- Task: KAI-1
- Deciders: Vijay (to accept)

## Context

The brief fixes the provider and limits: OpenRouter, Claude Haiku 4.5, at most 600 output tokens per call, a USD 8 limit, token and cost tracking, and replayed responses in tests so CI makes no live calls. Bearing's `llm-gateway` template implements an Anthropic provider and a FakeProvider; OpenRouter appears only as a commented route, and there is no cumulative budget.

## Options considered

### Option A: Gateway per Bearing's template with an OpenRouter provider, a persisted cost ledger and record or replay mode
`complete()` is the only call site. The provider speaks the OpenAI-compatible API at `https://openrouter.ai/api/v1`. Cost comes from the response's usage. The ledger refuses any call whose worst case (input tokens plus 600 output tokens at list price) would cross USD 8.

### Option B: Rely on the OpenRouter key's own credit limit
Simple, but the limit fails only after the fact, is invisible to tests, and does not record per-feature cost.

## Decision

We will build Option A and also set an USD 8 limit on the OpenRouter key as a second guard.

## Consequences

- Tests and CI run with `LLM_MODE=replay`; a missing recording fails with its hash.
- Recording needs `OPENROUTER_API_KEY` in a local or cloud session, never in CI.
- Revisit if a second model is needed (judge or fallback).
