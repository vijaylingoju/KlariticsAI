"""Bearer-token check for the MCP server's HTTP transport."""

import hmac

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Refuse every request without `Authorization: Bearer <token>`."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        super().__init__(app)
        self._expected = f"Bearer {token}".encode()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Constant-time comparison; 401 with no detail on a mismatch."""
        given = request.headers.get("authorization", "").encode()
        if not hmac.compare_digest(given, self._expected):
            return JSONResponse({"error": {"code": "unauthorized"}}, status_code=401)
        return await call_next(request)
