"""Shared HTTP security, destination guard, timeout, and status classification policy for `ext` sessions.

Zero `[auth]` or `pydantic` imports so the base package remains lightweight.
"""

from __future__ import annotations

import importlib.resources
import json
import re
import ssl
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import httpx

from compose_api_client.ext.errors import (
    ApiError,
    AuthError,
    CliError,
    ConfigError,
    ForbiddenError,
    InvalidRequestError,
    NotFoundError,
    ProtocolError,
    RateLimitedError,
    ServerError,
    ServiceUnavailableError,
    UncertainOutcomeError,
)
from compose_api_client.models import HTTPValidationError

TIMEOUT: Final = httpx.Timeout(60.0, connect=5.0, pool=5.0)  # read and write 60 s
COMMAND_DEADLINE_SECONDS: Final = 90.0
MAX_RETRY_AFTER_SECONDS: Final = 86400
MAX_VALIDATION_FIELDS: Final = 5
_FIELD_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    replayable: bool  # safe to send twice: a read, with no effect on the server

    def __str__(self) -> str:
        return f"{self.method} {self.path}"


CURRENT_PRINCIPAL: Final = Operation("GET", "/auth/me", replayable=True)
SIMULATOR_LIST: Final = Operation("GET", "/core/simulator/list", replayable=True)
SIMULATION_STATUS: Final = Operation("GET", "/results/simulation/status", replayable=True)
RUN_SIMULATION: Final = Operation("POST", "/simulation/run", replayable=False)

# All 9 mutating POST operations across the v0.7.25/v0.7.26 API surface.
NON_REPLAYABLE_OPERATIONS: Final[frozenset[tuple[str, str]]] = frozenset({
    ("POST", "/simulation/run"),
    ("POST", "/curated/copasi"),
    ("POST", "/curated/tellurium"),
    ("POST", "/sedml/run"),
    ("POST", "/sources/biomodels/{model_id}/run"),
    ("POST", "/sources/biosimulations/{project_id}/run"),
    ("POST", "/suites/{name}/run"),
    ("POST", "/registry/environments/{name}/build"),
    ("POST", "/registry/simulators/{simulator_id}/build"),
})

_UNKNOWN_OUTCOME = (
    "The simulation may or may not have been created: do not submit again blindly; check the server's simulations first"
)


class UnsafeRequestError(Exception):
    """A request was about to leave for somewhere other than this profile's API operations. Never sent."""


@dataclass(frozen=True)
class _Answer:
    status: int
    parsed: Any
    headers: httpx.Headers
    content: bytes = b""


_UNREADABLE: Final = object()  # a body the generated model could not parse


def _template_to_regex(template: str) -> re.Pattern[str]:
    """Compile an OpenAPI path template (e.g. `/datasets/{dataset_id}/files/{subpath}`) to a strict path regex."""
    parts = re.split(r"(\{[^}]+\})", template)
    pattern_parts: list[str] = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            # `{subpath}` can contain slashes; single-segment IDs cannot.
            pattern_parts.append(r".+" if name == "subpath" else r"[^/]+")
        else:
            pattern_parts.append(re.escape(part))
    return re.compile("^" + "".join(pattern_parts) + "$")


@lru_cache(maxsize=1)
def spec_path_patterns() -> tuple[re.Pattern[str], ...]:
    """Regexes for every path in the bundled `openapi.json`."""
    text = importlib.resources.files("compose_api_client").joinpath("openapi.json").read_text()
    spec = json.loads(text)
    paths = list(spec.get("paths", {}).keys())
    if "/auth/me" not in paths:
        paths.append("/auth/me")
    return tuple(_template_to_regex(p) for p in paths)


ALLOWED_PATHS: Final = frozenset(
    op.path for op in (CURRENT_PRINCIPAL, SIMULATOR_LIST, SIMULATION_STATUS, RUN_SIMULATION)
)


class _DestinationGuard:
    """Request event hook verifying scheme, host, port, absence of userinfo, and allowed API path."""

    def __init__(self, base_url: str, *, allowed_paths: frozenset[str] | None = None) -> None:
        origin = urlsplit(base_url)
        self.origin = (origin.scheme, origin.hostname, origin.port)
        self.allowed_paths = allowed_paths
        self._patterns = None if allowed_paths is not None else spec_path_patterns()

    def check(self, request: httpx.Request) -> None:
        url = request.url
        if (url.scheme, url.host, url.port) != self.origin or url.userinfo:
            raise UnsafeRequestError
        if self.allowed_paths is not None:
            if url.path not in self.allowed_paths:
                raise UnsafeRequestError
        elif self._patterns is not None and not any(pattern.fullmatch(url.path) for pattern in self._patterns):
            raise UnsafeRequestError

    def __call__(self, request: httpx.Request) -> None:
        self.check(request)

    async def async_hook(self, request: httpx.Request) -> None:
        self.check(request)


def tls_verification(ca_bundle: Path | None) -> ssl.SSLContext | bool:
    """System trust, extended by the profile's CA bundle when it names one. Verification is never switched off."""
    if ca_bundle is None:
        return True
    try:
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=str(ca_bundle))
        return context
    except (OSError, ssl.SSLError):
        raise ConfigError(f"ca_bundle ({ca_bundle}) is not a readable PEM file of CA certificates") from None


def rejected_message(*, renewable: bool, env_var: str | None = None) -> str:
    if env_var is not None:
        return (
            f"the API rejected the credentials in {env_var}; check that the token is valid, unexpired, and issued"
            " for this server's audience"
        )
    detail = "even after renewing the session" if renewable else "and this session cannot be renewed"
    return (
        f"the API rejected this session's credentials {detail}; sign in again. If that keeps happening, check that"
        " the profile's auth0_domain and auth0_audience match the API at api_base_url"
    )


def unanswered(operation: Operation, what: str) -> str:
    message = f"the API {what} ({operation})"
    return message if operation.replayable else f"{message}. {_UNKNOWN_OUTCOME}"


def classify_failure(
    operation: Operation,
    answer: _Answer,
    *,
    not_found: str | None = None,
) -> CliError:
    status = answer.status
    unknown = "" if operation.replayable else f" {_UNKNOWN_OUTCOME}."
    if 300 <= status < 400:
        return ProtocolError(
            f"the API answered {operation} with a redirect (HTTP {status}); credentials are never sent to a redirect."
            " Check api_base_url"
        )
    if status == 401:
        return AuthError(rejected_message(renewable=False))
    if status == 403:
        return ForbiddenError(
            f"the API refused {operation} for this account (HTTP 403); signing in again will not change that"
        )
    if status == 404:
        return NotFoundError(
            not_found or f"the API has no {operation} (HTTP 404); check api_base_url", status_code=status
        )
    if status in (400, 422):
        fields = invalid_fields(answer.parsed)
        where = f" ({', '.join(fields)})" if fields else ""
        return InvalidRequestError(
            f"the API rejected the request as invalid{where} (HTTP {status} from {operation})", status_code=status
        )
    if status == 429:
        wait = retry_after(answer.headers.get("retry-after"))
        hint = f"retry after {wait} s" if wait is not None else "wait a little and try again"
        return RateLimitedError(f"the API is rate limiting requests (HTTP 429 from {operation}); {hint}")
    if status in (502, 503, 504):
        return ServiceUnavailableError(
            f"the API is unavailable (HTTP {status} from {operation}); try again later.{unknown}", status_code=status
        )
    if status >= 500:
        return ServerError(f"the API failed while handling {operation} (HTTP {status}).{unknown}", status_code=status)
    return ApiError(f"the API answered {operation} with HTTP {status}", status_code=status)


def invalid_fields(parsed: Any) -> list[str]:
    """Where the API says the request was invalid, as field paths only: never its messages or the input it echoes."""
    if not isinstance(parsed, HTTPValidationError) or not isinstance(parsed.detail, list):
        return []
    fields: list[str] = []
    for item in parsed.detail[:MAX_VALIDATION_FIELDS]:
        parts = [str(part) for part in getattr(item, "loc", [])]
        if parts and all(_FIELD_NAME.fullmatch(part) for part in parts):
            fields.append(".".join(parts))
    return fields


def retry_after(value: str | None) -> int | None:
    """A Retry-After given in seconds, if it is a sane one. HTTP dates and anything unbounded are not shown."""
    if value is None or not value.strip().isdigit():
        return None
    seconds = int(value.strip())
    return seconds if seconds <= MAX_RETRY_AFTER_SECONDS else None


__all__ = [
    "ALLOWED_PATHS",
    "COMMAND_DEADLINE_SECONDS",
    "CURRENT_PRINCIPAL",
    "MAX_RETRY_AFTER_SECONDS",
    "MAX_VALIDATION_FIELDS",
    "NON_REPLAYABLE_OPERATIONS",
    "RUN_SIMULATION",
    "SIMULATION_STATUS",
    "SIMULATOR_LIST",
    "TIMEOUT",
    "_UNKNOWN_OUTCOME",
    "_UNREADABLE",
    "Operation",
    "UncertainOutcomeError",
    "UnsafeRequestError",
    "_Answer",
    "_DestinationGuard",
    "classify_failure",
    "invalid_fields",
    "rejected_message",
    "retry_after",
    "spec_path_patterns",
    "tls_verification",
    "unanswered",
]
