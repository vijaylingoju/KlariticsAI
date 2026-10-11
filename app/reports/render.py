"""A saved answer as Markdown or as a standalone HTML page.

HTML escapes every value that came from a question, the model or the data;
charts render client-side with vega-embed from their inline specs.
"""

import html
import json
from typing import Any

from app.agent.analyst import Answer, ContributionRow

VEGA = (
    '<script src="https://cdn.jsdelivr.net/npm/vega@5.30.0"></script>'
    '<script src="https://cdn.jsdelivr.net/npm/vega-lite@5.21.0"></script>'
    '<script src="https://cdn.jsdelivr.net/npm/vega-embed@6.26.0"></script>'
)

STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;"
    "line-height:1.5}table{border-collapse:collapse;width:100%;font-size:.9rem}"
    "td,th{border-bottom:1px solid #ddd;padding:.3rem;text-align:left}"
    "pre{background:#f6f6f6;padding:.5rem;overflow-x:auto}.chart{margin:1rem 0}"
)


def _num(value: float | None, digits: int = 4) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _table_rows(rows: list[ContributionRow]) -> list[list[str]]:
    return [
        [
            r.dimension,
            r.segment,
            _num(r.baseline_value),
            _num(r.current_value),
            _num(r.contribution),
            f"{r.share_of_change:.0%}",
            f"{r.explained:.2f}",
            f"{r.separation_z:.1f}",
            "yes" if r.likely_cause else "",
        ]
        for r in rows
    ]


HEADERS = [
    "Dimension",
    "Segment",
    "Baseline",
    "Current",
    "Contribution",
    "Share",
    "Explained",
    "z",
    "Cause",
]


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown(answer: Answer) -> str:
    """The report as Markdown."""
    lines = [f"# {_md_cell(answer.question)}", "", answer.narrative, ""]
    if answer.intent and answer.intent.assumptions:
        lines += ["## Assumptions", "", *[f"- {a}" for a in answer.intent.assumptions], ""]
    if answer.contribution_table:
        lines += [
            "## Contributions",
            "",
            "| " + " | ".join(HEADERS) + " |",
            "|" + "---|" * len(HEADERS),
        ]
        lines += [
            "| " + " | ".join(_md_cell(c) for c in row) + " |"
            for row in _table_rows(answer.contribution_table)
        ]
        lines.append("")
    if answer.charts:
        lines += ["## Charts", ""]
        for chart in answer.charts:
            lines += [
                f"### {_md_cell(chart.get('title', 'Chart'))}",
                "",
                "```json",
                json.dumps(chart, indent=1),
                "```",
                "",
            ]
    lines += ["## Tool calls", ""]
    for call in answer.tool_calls:
        status = "ok" if call.ok else f"error {(call.error or {}).get('code', '')}"
        lines.append(
            f"{call.index}. `{call.tool}` by {call.caller}, {status}, {call.duration_ms} ms: "
            f"`{json.dumps(call.arguments, separators=(',', ':'))}`"
        )
    lines += [
        "",
        f"Concluded by {answer.concluded_by}"
        + (f" (fallback: {answer.fallback_reason})" if answer.fallback_reason else "")
        + f". Model calls {answer.llm.calls}, tokens {answer.llm.input_tokens} in and "
        f"{answer.llm.output_tokens} out, cost USD {answer.llm.cost_usd:.4f}.",
    ]
    if answer.removed_sentences:
        lines += [
            "",
            f"{len(answer.removed_sentences)} sentence(s) removed: "
            "a number in them was not in the evidence.",
        ]
    return "\n".join(lines) + "\n"


def _cell(value: object) -> str:
    return html.escape(str(value))


def page(answer: Answer) -> str:
    """The report as one HTML page."""
    e = html.escape
    rows = "".join(
        "<tr>" + "".join(f"<td>{_cell(c)}</td>" for c in row) + "</tr>"
        for row in _table_rows(answer.contribution_table)
    )
    table = (
        "<h2>Contributions</h2><table><thead><tr>"
        f"{''.join(f'<th>{h}</th>' for h in HEADERS)}</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        if rows
        else ""
    )
    charts = "".join(f'<div class="chart" id="chart{i}"></div>' for i in range(len(answer.charts)))
    specs: list[dict[str, Any]] = answer.charts
    # Inside a <script>, "</" must not appear literally; JSON allows the escaped form.
    data = json.dumps(specs).replace("</", "<\\/")
    calls = "".join(
        f"<li><code>{e(c.tool)}</code> by {e(c.caller)}, "
        f"{'ok' if c.ok else 'error'}, {c.duration_ms} ms"
        f"<pre>{e(json.dumps(c.arguments, indent=1))}</pre></li>"
        for c in answer.tool_calls
    )
    assumptions = "".join(
        f"<li>{e(a)}</li>" for a in (answer.intent.assumptions if answer.intent else [])
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(answer.question)}</title>{VEGA}
<style>{STYLE}</style></head>
<body><h1>{e(answer.question)}</h1><p>{e(answer.narrative)}</p>
{f"<h2>Assumptions</h2><ul>{assumptions}</ul>" if assumptions else ""}
{charts}{table}<h2>Tool calls</h2><ol>{calls}</ol>
<p>Concluded by {e(answer.concluded_by)}. Model cost USD {answer.llm.cost_usd:.4f}.</p>
<script>const specs = {data};
specs.forEach((s, i) => vegaEmbed('#chart' + i, s, {{actions: false}}));</script>
</body></html>
"""
