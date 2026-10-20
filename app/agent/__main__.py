"""Ask the analyst from a terminal: `python -m app.agent "Why did purchases drop last week?"`.

Prints the answer as Markdown; `--json` prints the full answer, `--save` stores it as a report.
"""

import argparse
import asyncio
import sys

from app.agent.analyst import Analyst
from app.analytics.service import AnalyticsService
from app.analytics.store import connect_read_only
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.llm.gateway import gateway_from_settings, killed_features
from app.llm.ledger import Ledger
from app.mcp_server.server import build_server
from app.reports.render import markdown
from app.reports.store import ReportStore


async def _ask(question: str, as_json: bool, save: bool) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    gateway = gateway_from_settings(
        settings,
        settings.llm_mode,
        Ledger(settings.llm_ledger_path, settings.llm_budget_usd),
        disabled=killed_features(),
    )
    service = AnalyticsService(connect_read_only(settings.store_path))
    answer = await Analyst(build_server(service), gateway).ask(question)
    if save:
        answer = ReportStore(settings.reports_dir).save(answer)
    sys.stdout.write(answer.model_dump_json(indent=1) if as_json else markdown(answer))
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and answer one question."""
    parser = argparse.ArgumentParser(prog="klaritics-ask")
    parser.add_argument("question")
    parser.add_argument("--json", action="store_true", help="print the full answer as JSON")
    parser.add_argument("--save", action="store_true", help="save the answer as a report")
    args = parser.parse_args(argv)
    return asyncio.run(_ask(args.question, args.json, args.save))


if __name__ == "__main__":
    raise SystemExit(main())
