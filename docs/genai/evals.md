# Evals

## Analyst (`evals/analyst`, agent)

| | |
| --- | --- |
| Metric | Root-cause accuracy over 45 cases (15 questions, 2 paraphrases each); target 0.87 (13 of 15, Q-001) |
| Also scored | Intent accuracy, numeric accuracy (headline numbers against the store), paraphrase consistency, fallback rate, tool calls, cost, p95 latency |
| Labels | From the planted ground truth (`ground_truth.json`); owner to confirm |
| Graders | 4, all deterministic (`evals/analyst/graders.py`); no model judges |
| Gate | `evals/analyst/gate.json`: root cause >= 0.87, numbers >= 0.95, intent >= 0.9, at most 8 tool calls, 0 errors |
| Run | `make eval` (replay, no network); `make eval-record` records live answers |

### Status

| Run | Root cause | Intent | Numbers | Fallback | Cost | Accepted |
| --- | --- | --- | --- | --- | --- | --- |
| Perfect-reader check (`tests/evals`, every commit) | 15/15 | 1.00 | 1.00 | 0.00 | 0 | n/a |
| Haiku 4.5, recorded | not run: needs OpenRouter access to record | | | | | |

The perfect-reader check answers each case exactly as labelled and proves
the scenarios, tools, fallback rules and graders agree with the labels. It
says nothing about what the model understands; the recorded run does.

### Recording

1. A cloud environment with `openrouter.ai` allowed and `OPENROUTER_API_KEY` set.
2. `make eval-record`: about 45 x 4 model calls, estimated under USD 1.
3. Commit `evals/recordings/`; `make eval` then replays them with no network.
4. Add the CI job (`eval`, `make eval`) once recordings are committed, so it
   never runs against an empty set.

A prompt, tool description or catalogue change changes request hashes, and
`make eval` then fails with the missing hash: record again.
