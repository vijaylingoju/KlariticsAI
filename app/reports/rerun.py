"""Re-run a saved report's tool calls and compare every result with what was saved."""

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from app.agent.analyst import Answer
from mcp import Client


class RerunResult(BaseModel):
    """Whether the saved numbers reproduce."""

    report_id: str
    calls: int
    reproduced: bool
    differences: list[str]


async def rerun(answer: Answer, target: MCPServer | str) -> RerunResult:
    """Call every logged tool again with the same arguments; any change in a result is listed."""
    differences: list[str] = []
    async with Client(target) as client:
        for call in answer.tool_calls:
            result = await client.call_tool(call.tool, call.arguments)
            if result.is_error != (not call.ok):
                differences.append(f"call {call.index} {call.tool}: success changed")
            elif call.ok and result.structured_content != call.result:
                differences.append(f"call {call.index} {call.tool}: result changed")
    return RerunResult(
        report_id=answer.id or "",
        calls=len(answer.tool_calls),
        reproduced=not differences,
        differences=differences,
    )
