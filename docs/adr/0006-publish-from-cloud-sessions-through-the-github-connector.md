# ADR-0006: Publish branches from cloud sessions through the GitHub connector

- Status: Proposed
- Date: 2026-10-11
- Task: KAI-1
- Deciders: Vijay (to accept)

## Context

The owner wants the build to run in Claude Code cloud sessions while away from a laptop. Bearing's guard blocks `git push` and `gh pr create` because an engineer is expected to push. In a cloud session nobody sits at that terminal. The repository's sandbox allowlist also lacks the model provider host.

## Options considered

### Option A: Push task branches and open draft pull requests from the session, never merge
The session publishes `feature/KAI-*` branches and draft pull requests; the owner reviews and merges. Merges, force pushes and pushes to `main` stay blocked.

### Option B: The owner pushes every change by hand
Matches Bearing exactly, but stalls all work while the owner is away.

## Decision

We will use Option A and record it here. `openrouter.ai` is added to the sandbox network allowlist in `.claude/settings.json`.

## Consequences

- The owner remains the only one who merges.
- Proposed to Bearing as a supported "remote push to task branch" mode.
