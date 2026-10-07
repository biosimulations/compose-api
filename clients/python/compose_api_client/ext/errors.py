"""Typed errors for the application layer, mapped from the generated client's detailed responses."""

from __future__ import annotations

import json
from typing import Any

from compose_api_client.types import Response


class ComposeApiError(Exception):
    """An unexpected response from compose-api: ``status_code`` and the decoded ``detail``."""

    def __init__(self, status_code: int, detail: Any, message: str | None = None) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(message or f"compose-api returned {status_code}: {detail}")


class BadRequest(ComposeApiError):
    """400 or 422. ``violations`` lists the document validation errors when the service reports them
    (`POST /simulation/run` answers ``{"detail": {"message": ..., "violations": [...]}}``)."""

    @property
    def violations(self) -> list[Any]:
        if isinstance(self.detail, dict):
            v = self.detail.get("violations")
            return list(v) if isinstance(v, list) else []
        return []


class NotFound(ComposeApiError):
    """404."""


class ServerError(ComposeApiError):
    """5xx."""


class ApiTimeout(TimeoutError):
    """A wait ran past its deadline. ``last`` is the last state seen, if any."""

    def __init__(self, message: str, last: Any = None) -> None:
        self.last = last
        super().__init__(message)


def detail_of(content: bytes) -> Any:
    """FastAPI's ``detail`` from an error body; the raw text when the body is not JSON."""
    try:
        body = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return content.decode(errors="replace")
    return body.get("detail", body) if isinstance(body, dict) else body


def raise_for(response: Response[Any]) -> None:
    """Raise the typed error for a non-2xx response."""
    code = int(response.status_code)
    if 200 <= code < 300:
        return
    detail = detail_of(response.content)
    if code in (400, 422):
        raise BadRequest(code, detail)
    if code == 404:
        raise NotFound(code, detail)
    if code >= 500:
        raise ServerError(code, detail)
    raise ComposeApiError(code, detail)
