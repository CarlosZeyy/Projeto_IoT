"""Pure ASGI middlewares of the edge gateway (SPEC-007 sections 4.5 and 4.7).

* ``BodySizeLimitMiddleware``: 413 for a declared ``Content-Length`` above the limit, before the
  body is read; chunked bodies are counted as they arrive.
* ``UnhandledErrorMiddleware``: unexpected exception -> 500 ``{"detail": "internal server
  error"}``, without stack trace in the response; the traceback goes only to the server log.
* ``RequestLogMiddleware``: one line per request (method, route, status, duration). The query
  string, where the page carries the session token, is never logged (R-03).
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import HTTPException, status
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("qc_edge")

DETAIL_REQUEST_TOO_LARGE = "request body too large"
DETAIL_INTERNAL = "internal server error"
_MAX_LOGGED_PATH = 200


class RequestTooLargeError(HTTPException):
    """Raised from ``receive`` when a body without a usable ``Content-Length`` passes the limit.

    An ``HTTPException`` so the app's exception handling renders it as 413 when it surfaces
    while the form is being parsed.
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=DETAIL_REQUEST_TOO_LARGE
        )


async def _send_json(send: Send, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


class BodySizeLimitMiddleware:
    """Refuse request bodies larger than ``limit`` bytes with 413."""

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self.limit:
            await _send_json(send, status.HTTP_413_CONTENT_TOO_LARGE, DETAIL_REQUEST_TOO_LARGE)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise RequestTooLargeError()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except RequestTooLargeError:
            if response_started:
                raise
            await _send_json(send, status.HTTP_413_CONTENT_TOO_LARGE, DETAIL_REQUEST_TOO_LARGE)


class UnhandledErrorMiddleware:
    """Turn any unexpected exception into 500 ``{"detail": "internal server error"}``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            logger.exception("unhandled exception")
            if response_started:
                raise
            await _send_json(send, status.HTTP_500_INTERNAL_SERVER_ERROR, DETAIL_INTERNAL)


def _route_label(scope: Scope) -> str:
    """Route template when a route matched, else the raw path (``repr``, truncated)."""
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str):
        return template
    return repr(str(scope.get("path", ""))[:_MAX_LOGGED_PATH])


class RequestLogMiddleware:
    """Log ``method route status duration`` for every HTTP request, never the query string."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status_code = 500
        started = time.perf_counter()

        async def tracking_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        finally:
            logger.info(
                "%s %s %d %.1fms",
                scope.get("method", "-"),
                _route_label(scope),
                status_code,
                (time.perf_counter() - started) * 1000,
            )
