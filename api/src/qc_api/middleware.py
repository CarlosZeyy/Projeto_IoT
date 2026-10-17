"""Pure ASGI middlewares (SPEC-004 sections 4.2 and 4.5).

* ``BodySizeLimitMiddleware``: 413 for bodies above ``MAX_BODY_BYTES``, on every route.
* ``UnhandledErrorMiddleware``: unexpected exception -> 500 ``Internal server error``; the
  traceback goes only to the server log. A database error (``psycopg.Error``, also when wrapped
  in another exception) is logged as one line with the route, the class and the SQLSTATE, never
  the message nor the traceback, which may carry row values (SPEC-005 section 4.5,
  docs/architecture.md section 4, "Erros de banco no log").
* ``RequestLogMiddleware``: one log line per request (method, route, status, ``device_id``,
  duration). Never the ``X-API-Key``, the body or a key hash.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable

import psycopg
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from qc_api.errors import DETAIL_BODY_TOO_LARGE, DETAIL_INTERNAL, BodyTooLargeError

logger = logging.getLogger("qc_api")

_MAX_LOGGED_PATH = 200
_SQLSTATE_RE = re.compile(r"[0-9A-Z]{5}")


async def _send_json(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
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
    """Refuse request bodies larger than ``get_limit()`` bytes with 413.

    A declared ``Content-Length`` above the limit is refused without reading the body. Otherwise
    (chunked bodies included) the bytes are counted as they are read, and ``BodyTooLargeError``
    is raised from ``receive`` as soon as the limit is passed.
    """

    def __init__(self, app: ASGIApp, get_limit: Callable[[], int]) -> None:
        self.app = app
        self.get_limit = get_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.get_limit()
        declared = _declared_length(scope)
        if declared is not None and declared > limit:
            await _send_json(send, 413, DETAIL_BODY_TOO_LARGE)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLargeError()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLargeError:
            # The body was read outside FastAPI's exception handling; answer here if possible.
            if response_started:
                raise
            await _send_json(send, 413, DETAIL_BODY_TOO_LARGE)


def find_database_error(exc: BaseException) -> psycopg.Error | None:
    """First ``psycopg.Error`` in ``exc`` or its ``__cause__``/``__context__`` chain.

    The search is depth-first, ``__cause__`` before ``__context__``, and also looks inside
    exception groups. A suppressed context (``raise ... from None``) is still searched: the
    rule is conservative. Cycles are followed only once.
    """
    stack: list[BaseException] = [exc]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, psycopg.Error):
            return current
        # Pushed in reverse so the pop order is: group members, then cause, then context.
        if current.__context__ is not None:
            stack.append(current.__context__)
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if isinstance(current, BaseExceptionGroup):
            stack.extend(reversed(current.exceptions))
    return None


def sqlstate_label(exc: psycopg.Error) -> str:
    """The SQLSTATE of ``exc`` (five digits or capital letters), or ``-`` when there is none."""
    sqlstate = getattr(exc, "sqlstate", None)
    if isinstance(sqlstate, str) and _SQLSTATE_RE.fullmatch(sqlstate):
        return sqlstate
    return "-"


class UnhandledErrorMiddleware:
    """Turn any unexpected exception into 500 ``{"detail": "Internal server error"}``.

    Database errors are logged without ``exc_info`` and without their message (see the module
    docstring); any other exception keeps ``logger.exception``.
    """

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
        except Exception as exc:
            database_error = find_database_error(exc)
            if database_error is None:
                logger.exception("unhandled exception")
                if response_started:
                    raise
            else:
                logger.error(
                    "unhandled database error: route=%s type=%s sqlstate=%s",
                    _route_label(scope),
                    type(database_error).__name__,
                    sqlstate_label(database_error),
                )
                if response_started:
                    # Whoever logs this one (the server) must not print the database error.
                    raise RuntimeError("unhandled database error") from None
            await _send_json(send, 500, DETAIL_INTERNAL)


def _route_label(scope: Scope) -> str:
    """Route template when a route matched (e.g. ``/api/v1/inspections``), else the raw path."""
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str):
        return template
    return repr(str(scope.get("path", ""))[:_MAX_LOGGED_PATH])


class RequestLogMiddleware:
    """Log ``method route status device_id duration`` for every HTTP request.

    ``device_id`` comes from ``request.state.device_id`` (set by ``require_device``), which
    Starlette keeps in ``scope["state"]``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
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
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "%s %s %d device_id=%s %.1fms",
                scope.get("method", "-"),
                _route_label(scope),
                status_code,
                state.get("device_id") or "-",
                duration_ms,
            )
