# Progress: KAI-3 M3: evals

- Task: KAI-3
- Title: M3: evals
- Branch: feature/KAI-3-M3Evals
- Status: merged
- Owner: Vijay (vijaylingoju)
- Started: 2026-10-11
- Updated: 2026-10-11
- Acceptance criteria: docs/product/stories.md EP-07: TC-0500 to TC-0504 pass; EVAL not run

## Next
- record eval answers with make eval-record in an OpenRouter session, commit evals/recordings/, then add the CI eval job

## Done
- 45 graded cases, 4 deterministic graders, gate in evals/analyst/gate.json
- perfect-reader pipeline check runs on every commit (tests/evals/)
- merged to main in PR #1 on 2026-10-11, squashed with KAI-1 and KAI-2 (per the owner)

## Blockers
- real eval recording pending: needs an OpenRouter session with OPENROUTER_API_KEY (Vijay)
- CI eval job pending until recordings are committed (Vijay)

## Decisions
- cloud publishing: docs/adr/0006-publish-from-cloud-sessions-through-the-github-connector.md (Proposed)

## Links
- MR: https://github.com/vijaylingoju/klariticsai/pull/1
- Ticket: none
