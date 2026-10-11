# ADR-0005: Run the agent as an intent-first bounded workflow loop

- Status: Proposed
- Date: 2026-10-11
- Task: KAI-1
- Deciders: Vijay (to accept)

## Context

The agent must pick analyses by the user's intent, stop after eight tool calls, fall back to a deterministic plan, and never state an unsupported number. Bearing's `llm-agent` defaults to the Anthropic SDK tool runner, which OpenRouter does not serve, and recommends a manual loop for the `workflow` type. It advises against LangGraph by default.

## Options considered

### Option A: Manual loop over OpenAI-style tool calls, intent parsed first
Step 1 parses the question into a validated Intent. Step 2 runs a tool loop with a hard counter of 8. Step 3 validates numbers in code. Any failure routes to the deterministic contribution plan.

### Option B: LangGraph graph
The team's older service used it, but it is a second runtime to test and trace for a three-step flow.

## Decision

We will use Option A. A cheaper option, a single prompt with no tools, was rejected because the model cannot compute contributions over a million events from a prompt.

## Consequences

- The loop bound and the fallback are plain code with plain tests.
- Revisit if the flow grows branches the state machine cannot express clearly.
