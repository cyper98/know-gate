"""ASGI middleware: capture client IP from X-Forwarded-For (if behind proxy).

Stores IP on `request.state.client_ip` so endpoint handlers and audit
loggers can read it without re-parsing headers.
"""

from __future__ import annotations

from collections.abc import Callable

from starlette.requests import Request


def get_client_ip(request: Request) -> str | None:
    """Extract client IP from X-Forwarded-For (first hop) or fall back to client.host."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # X-Forwarded-For: client, proxy1, proxy2 — take the first
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return None


class ClientIPMiddleware:
    """ASGI middleware that injects `request.state.client_ip`.

    Use as:
        app.add_middleware(ClientIPMiddleware)
    Then in endpoint:
        client_ip = request.state.client_ip
    """

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(
        self, scope: dict, receive: Callable, send: Callable
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        request.state.client_ip = get_client_ip(request)

        async def wrapped_receive() -> dict:
            return await receive()

        await self.app(scope, wrapped_receive, send)
