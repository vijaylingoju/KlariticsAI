"""Run the MCP server: `python -m app.mcp_server [--transport stdio|http]`.

stdio writes only protocol frames to stdout; logs go to stderr. HTTP requires
MCP_HTTP_TOKEN and serves streamable HTTP at /mcp.
"""

import argparse
import sys

import structlog
import uvicorn

from app.analytics.service import AnalyticsService
from app.analytics.store import connect_read_only
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.mcp_server.auth import BearerTokenMiddleware
from app.mcp_server.server import build_server


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, open the store, serve until stopped."""
    parser = argparse.ArgumentParser(prog="klaritics-mcp")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    service = AnalyticsService(connect_read_only(settings.store_path))
    server = build_server(service)
    if args.transport == "stdio":
        server.run("stdio")
        return 0
    if settings.mcp_http_token is None:
        structlog.get_logger().error("MCP_HTTP_TOKEN is required for the HTTP transport")
        return 2
    app = server.streamable_http_app(host="0.0.0.0")
    app.add_middleware(BearerTokenMiddleware, token=settings.mcp_http_token.get_secret_value())
    uvicorn.run(app, host="0.0.0.0", port=settings.mcp_http_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
