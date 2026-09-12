"""Unified HTTP error plumbing (issue #97 / ticket #100).

Design contract, deliberately narrow:

- ``detail`` of existing ``HTTPException`` responses is preserved **byte for
    byte** (str or dict); the frontend (``static/app/events.js`` and the
    login path in ``main.js``) keeps reading it unchanged. ``request_id`` is
    an additive top-level field on every error response — that is the whole
    "附加式统一" from the spec; full error-code normalisation is deferred to
    the mid-priority track.
- Uncaught exceptions no longer reach Starlette's plain-text 500: they become
  ``{"code": "internal_error", "message": <fixed 话术>, "request_id": ...}``
  and emit one structured ``http.unhandled`` log record carrying the traceback
  server-side (the client must never see internal exception text).
- The request-id middleware in ``api/__init__.py`` stores the id on
  ``request.state`` **and** binds the observability ContextVar. Handlers read
  state first: the generic ``Exception`` handler runs in Starlette's
  ServerErrorMiddleware, which sits *outside* the user middleware, so the
  ContextVar may already be reset there while ``state`` survives on the
  shared scope dict.

OpenAPI footprint is intentionally zero: no route gains a ``responses=``
declaration, so the frozen contract snapshot stays untouched (grilling
decision: the runtime contract tests are the shape lock).
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..observability import current_request_id, log_event, new_request_id

logger = logging.getLogger("resualign.api")

INTERNAL_ERROR_CODE = "internal_error"
INTERNAL_ERROR_MESSAGE = "服务器内部错误，请稍后重试；若持续出现请提供请求编号"


def request_id_of(request: Request) -> str:
    """The id bound for this request: middleware state first, ContextVar next.

    Falls back to a fresh id only when neither is set (e.g. an app mounted
    without the request-id middleware), so error bodies always carry one.
    """
    try:
        rid = request.state.request_id
    except AttributeError:
        rid = None
    return rid or current_request_id() or new_request_id()


def _stamp(
    body: dict[str, Any], request: Request
) -> tuple[dict[str, Any], dict[str, str]]:
    """Attach ``request_id`` to the body and return matching headers."""
    rid = request_id_of(request)
    body["request_id"] = rid
    return body, {"X-Request-Id": rid}


def register_error_handlers(app: FastAPI) -> None:
    """Install the three handlers that make every HTTP error JSON-shaped."""

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        content, headers = _stamp({"detail": exc.detail}, request)
        if exc.headers:
            headers = {**dict(exc.headers), **headers}
        return JSONResponse(
            status_code=exc.status_code, content=content, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Mirror FastAPI's default body exactly, then append request_id.
        content, headers = _stamp({"detail": jsonable_encoder(exc.errors())}, request)
        return JSONResponse(status_code=422, content=content, headers=headers)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        content, headers = _stamp(
            {"code": INTERNAL_ERROR_CODE, "message": INTERNAL_ERROR_MESSAGE},
            request,
        )
        log_event(
            logger,
            "http.unhandled",
            level="error",
            request_id=headers["X-Request-Id"],
            extra={
                "method": request.method,
                "path": request.url.path,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ),
            },
        )
        return JSONResponse(status_code=500, content=content, headers=headers)
