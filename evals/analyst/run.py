"""Run the analyst eval: every case through the real analyst, graded in code.

    uv run python -m evals.analyst.run              # replay: recorded answers, no network (CI)
    uv run python -m evals.analyst.run --mode record  # live calls, saved for replay (needs a key)
    uv run python -m evals.analyst.run --only q05

Writes evals/analyst/results/<version>.jsonl (one graded row per case) and
<version>.summary.json, prints the summary, and exits 1 when a gate in
gate.json fails.
"""

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.agent.analyst import Analyst
from app.analytics.service import AnalyticsService
from app.analytics.store import connect_read_only
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.llm.gateway import Gateway, build_provider
from app.llm.ledger import Ledger
from app.llm.providers import ReplayProvider
from app.llm.types import LLMError, LLMRequest, LLMResponse
from app.mcp_server.server import build_server
from evals.analyst import graders

HERE = Path(__file__).resolve().parent


class Watch:
    """Passes calls to the gateway and remembers every failure, so none hides inside a fallback."""

    def __init__(self, gateway: Gateway) -> None:
        self.gateway = gateway
        self.errors: list[dict[str, Any]] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        """One model call; failures are recorded, then raised as usual."""
        try:
            return await self.gateway.complete(req)
        except LLMError as exc:
            self.errors.append(
                {
                    "feature": req.feature,
                    "code": exc.code,
                    **{k: str(v) for k, v in exc.details.items()},
                }
            )
            raise


def load_cases(only: str | None) -> list[dict[str, Any]]:
    """The golden set, optionally one group."""
    cases = [
        json.loads(line) for line in (HERE / "cases.jsonl").read_text().splitlines() if line.strip()
    ]
    return [c for c in cases if only is None or c["group"] == only or c["id"] == only]


def version() -> str:
    """Git short sha, or 'local' outside a checkout."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - git from PATH
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except OSError, subprocess.CalledProcessError:
        return "local"
    return sha or "local"


async def grade_case(
    case: dict[str, Any], analyst: Analyst, watch: Watch, service: AnalyticsService
) -> dict[str, Any]:
    """Ask, then grade. A crash or a model failure is an error row, never a skip."""
    errors_before = len(watch.errors)
    started = time.monotonic()
    try:
        answer = await analyst.ask(case["input"]["question"])
    except Exception as exc:
        return {"id": case["id"], "group": case["group"], "error": f"{type(exc).__name__}: {exc}"}
    latency_ms = int((time.monotonic() - started) * 1000)
    errors = watch.errors[errors_before:]
    grades = {
        "root_cause": graders.root_cause(case, answer),
        "intent": graders.intent_match(case, answer),
        "numbers": graders.numbers(case, answer, graders.truth(case, service)),
        "budget": graders.within_budget(answer),
    }
    return {
        "id": case["id"],
        "group": case["group"],
        "variant": case["variant"],
        "question": case["input"]["question"],
        "error": "; ".join(f"{e['feature']}: {e['code']}" for e in errors) or None,
        "llm_errors": errors,
        "scores": {k: g.score for k, g in grades.items()},
        "details": {k: g.detail for k, g in grades.items()},
        "kind": answer.kind,
        "concluded_by": answer.concluded_by,
        "fallback_reason": answer.fallback_reason,
        "resolved": graders.resolved(answer),
        "tool_calls": len(answer.tool_calls),
        "narrative": answer.narrative,
        "removed_sentences": len(answer.removed_sentences),
        "llm": answer.llm.model_dump(),
        "latency_ms": latency_ms,
    }


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    scores = [r["scores"][key] for r in rows if "scores" in r and r["scores"][key] is not None]
    return round(statistics.fmean(scores), 4) if scores else None


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Scores, consistency across paraphrases, fallback rate, cost and latency."""
    graded = [r for r in rows if "scores" in r]
    groups: dict[str, set[str]] = defaultdict(set)
    for r in graded:
        groups[r["group"]].add(json.dumps(r["resolved"], sort_keys=True))
    explain = [r for r in graded if r["kind"] == "explain_change"]
    latencies = sorted(r["latency_ms"] for r in graded) or [0]
    return {
        "cases": len(rows),
        "errors": sum(1 for r in rows if r.get("error")),
        "root_cause_accuracy": _mean(rows, "root_cause"),
        "root_cause_accuracy_base": _mean(
            [r for r in graded if r["variant"] == "base"], "root_cause"
        ),
        "intent_accuracy": _mean(rows, "intent"),
        "numeric_accuracy": _mean(rows, "numbers"),
        "paraphrase_consistency": round(
            sum(1 for v in groups.values() if len(v) == 1) / len(groups), 4
        )
        if groups
        else None,
        "fallback_rate": round(
            sum(1 for r in explain if r["concluded_by"] == "fallback") / len(explain), 4
        )
        if explain
        else None,
        "max_tool_calls": max((r["tool_calls"] for r in graded), default=0),
        "mean_tool_calls": round(statistics.fmean([r["tool_calls"] for r in graded]), 2)
        if graded
        else 0,
        "sentences_removed": sum(r["removed_sentences"] for r in graded),
        "cost_usd": round(sum(r["llm"]["cost_usd"] for r in graded), 4),
        "p95_latency_ms": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))],
    }


def check_gate(summary: dict[str, Any]) -> list[str]:
    """Every gate in gate.json the summary fails."""
    gate = json.loads((HERE / "gate.json").read_text())
    failures = []
    for key, rule in gate.items():
        value = summary.get(key)
        if value is None:
            failures.append(f"{key}: no value")
        elif "min" in rule and value < rule["min"]:
            failures.append(f"{key}: {value} < {rule['min']}")
        elif "max" in rule and value > rule["max"]:
            failures.append(f"{key}: {value} > {rule['max']}")
    return failures


async def main_async(mode: str | None, only: str | None) -> int:
    """Run, write results, print the summary, apply the gate."""
    settings = get_settings()
    configure_logging("warning", "console", stream=sys.stderr)
    llm_mode = mode or settings.llm_mode
    key = settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else None
    results = HERE / "results"
    results.mkdir(exist_ok=True)
    run_id = f"{version()}-{llm_mode}"
    gateway = Gateway(
        build_provider(llm_mode, key, ReplayProvider(settings.llm_recordings_dir)),
        # Replays cost nothing; live and record runs count against the real limit.
        Ledger(
            settings.llm_ledger_path
            if llm_mode != "replay"
            else results / f"{run_id}.ledger.jsonl",
            settings.llm_budget_usd,
        ),
    )
    watch = Watch(gateway)
    service = AnalyticsService(connect_read_only(settings.store_path))
    analyst = Analyst(build_server(service), watch)
    cases = load_cases(only)
    if not cases:
        sys.stderr.write("eval: 0 cases selected\n")
        return 1
    rows = [await grade_case(case, analyst, watch, service) for case in cases]
    summary = summarise(rows) | {"run": run_id, "mode": llm_mode, "accepted": False}
    (results / f"{run_id}.jsonl").write_text(
        "".join(json.dumps(r, default=str) + "\n" for r in rows)
    )
    (results / f"{run_id}.summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    for r in rows:
        mark = (
            "ERR "
            if r.get("error")
            else ("ok  " if r.get("scores", {}).get("root_cause") == 1.0 else "MISS")
        )
        sys.stdout.write(
            f"{mark} {r['id']:<10} {r.get('kind', '-'):<15} "
            f"{r.get('concluded_by', '-'):<9} {r.get('error') or ''}\n"
        )
    sys.stdout.write(json.dumps(summary, indent=1) + "\n")
    failures = check_gate(summary)
    for failure in failures:
        sys.stdout.write(f"gate failed: {failure}\n")
    sys.stdout.write(f"eval: {len(rows)} cases, gate {'passed' if not failures else 'FAILED'}\n")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(prog="eval-analyst")
    parser.add_argument("--mode", choices=["replay", "record", "live"])
    parser.add_argument("--only", help="one case id or group, e.g. q05")
    args = parser.parse_args(argv)
    return asyncio.run(main_async(args.mode, args.only))


if __name__ == "__main__":
    raise SystemExit(main())
