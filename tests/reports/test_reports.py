"""Saved reports: storage, rendering, reproduction and the HTTP API (US-06-002)."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from mcp.server.mcpserver import MCPServer

from app.agent.analyst import Analyst, Answer
from app.analytics.service import AnalyticsService
from app.api.analyst.router import get_analyst
from app.reports.render import markdown, page
from app.reports.rerun import rerun
from app.reports.store import ReportNotFoundError, ReportStore
from tests.agent.conftest import FUNNEL_DRAFT, QUESTION, ScriptedLLM, funnel_steps


def _analyst(server: MCPServer, service: AnalyticsService) -> Analyst:
    return Analyst(
        server,
        ScriptedLLM(
            [FUNNEL_DRAFT],
            steps=funnel_steps(service),
            narrative="Purchases fell on app version 5.4.0.",
        ),
    )


@pytest.fixture
async def answer(server: MCPServer, service: AnalyticsService) -> Answer:
    return await _analyst(server, service).ask(QUESTION)


def test_tc0400_saved_report_reads_back_identical(answer: Answer, tmp_path: Path) -> None:
    store = ReportStore(tmp_path)

    saved = store.save(answer)

    assert saved.id is not None
    assert store.get(saved.id) == saved
    assert [r.id for r in store.list()] == [saved.id]


@pytest.mark.parametrize("report_id", ["../../etc/passwd", "0123456789abcdef", "short"])
def test_tc0401_unknown_or_malformed_id_is_not_found(tmp_path: Path, report_id: str) -> None:
    with pytest.raises(ReportNotFoundError):
        ReportStore(tmp_path).get(report_id)


def test_tc0402_markdown_has_narrative_assumptions_table_charts_and_log(answer: Answer) -> None:
    text = markdown(answer)

    assert "Purchases fell on app version 5.4.0." in text
    assert "## Assumptions" in text
    assert "| Dimension | Segment |" in text
    assert "| app_version | 5.4.0 |" in text
    assert "vega-lite" in text
    assert "1. `compare_segments` by agent, ok" in text


def test_tc0403_html_escapes_everything_from_the_question_and_data(answer: Answer) -> None:
    hostile = answer.model_copy(
        update={"question": "<script>alert(1)</script>", "narrative": "</script><b>x</b>"}
    )

    html = page(hostile)

    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;/script&gt;&lt;b&gt;" in html
    assert html.count("</script>") == 4  # three vega bundles and the chart bootstrap


async def test_tc0404_rerun_reproduces_every_number(answer: Answer, server: MCPServer) -> None:
    result = await rerun(answer, server)

    assert (result.reproduced, result.calls, result.differences) == (True, 1, [])


async def test_tc0404_rerun_reports_a_changed_number(answer: Answer, server: MCPServer) -> None:
    call = answer.tool_calls[0]
    tampered_result = {**(call.result or {}), "change": 0.5}
    tampered = answer.model_copy(
        update={"tool_calls": [call.model_copy(update={"result": tampered_result})]}
    )

    result = await rerun(tampered, server)

    assert result.reproduced is False
    assert result.differences == ["call 1 compare_segments: result changed"]


@pytest.fixture
def scripted_app(app: FastAPI, server: MCPServer, service: AnalyticsService) -> FastAPI:
    app.dependency_overrides[get_analyst] = lambda: _analyst(server, service)
    return app


async def test_tc0410_api_answers_saves_and_serves_a_report(
    scripted_app: FastAPI, client: AsyncClient
) -> None:
    asked = await client.post("/v1/questions", json={"question": QUESTION, "save": True})
    report_id = asked.json()["id"]

    fetched = await client.get(f"/v1/reports/{report_id}")
    md = await client.get(f"/v1/reports/{report_id}/markdown")
    html = await client.get(f"/v1/reports/{report_id}/html")
    listed = await client.get("/v1/reports")

    assert asked.status_code == 200
    assert fetched.json()["cause"]["segment"] == "5.4.0"
    assert md.headers["content-type"].startswith("text/plain")
    assert "| app_version | 5.4.0 |" in md.text
    assert html.headers["content-type"].startswith("text/html")
    assert [r["id"] for r in listed.json()] == [report_id]


async def test_tc0411_api_rerun_reproduces_a_saved_report(
    scripted_app: FastAPI, client: AsyncClient
) -> None:
    report_id = (
        await client.post("/v1/questions", json={"question": QUESTION, "save": True})
    ).json()["id"]

    rerun_response = await client.post(f"/v1/reports/{report_id}/rerun")

    assert rerun_response.json()["reproduced"] is True


async def test_tc0412_unsaved_answer_has_no_id(scripted_app: FastAPI, client: AsyncClient) -> None:
    asked = await client.post("/v1/questions", json={"question": QUESTION})

    assert asked.json()["id"] is None
    assert (await client.get("/v1/reports")).json() == []


@pytest.mark.parametrize(
    ("body", "status"),
    [({"question": "hi"}, 422), ({"question": QUESTION, "answer": {}}, 422), ({}, 422)],
    ids=["too_short", "client_supplied_answer", "missing"],
)
async def test_tc0413_api_rejects_invalid_questions(
    client: AsyncClient, body: dict[str, object], status: int
) -> None:
    response = await client.post("/v1/questions", json=body)

    assert response.status_code == status


async def test_tc0414_unknown_report_is_404(client: AsyncClient) -> None:
    response = await client.get("/v1/reports/0123456789abcdef")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
