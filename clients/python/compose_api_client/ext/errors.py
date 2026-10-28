"""Exit codes and typed errors for the application layer and CLI.

A `CliError` message is printed verbatim, so it must already be safe to show: it names settings, sources and rules,
never a configured value, a token or a raw server response body.
"""

from __future__ import annotations

import json
from enum import IntEnum
from typing import Any, ClassVar

from compose_api_client.ext.json_types import JsonValue
from compose_api_client.types import Response


class ExitCode(IntEnum):
    """The process exit status contract. Scripts depend on these values; never renumber one."""

    OK = 0
    FAILURE = 1  # an unsuccessful API response or command outcome not covered below
    USAGE = 2  # malformed command line or unusable local argument
    AUTH_REQUIRED = 3
    FORBIDDEN = 4
    NETWORK = 5
    CONFIG = 6  # configuration, credential storage or protocol errors
    WAIT_TIMEOUT = 7  # a wait ran past its deadline
    CANCELLED = 130


class CliError(Exception):
    """An expected failure with a message that is safe to print."""

    exit_code: ClassVar[ExitCode] = ExitCode.FAILURE
    category: ClassVar[str] = "failure"

    def __init__(self, message: str, *, exit_code: ExitCode | None = None) -> None:
        super().__init__(message)
        self.message = message
        if exit_code is not None:
            self.exit_code = exit_code  # type: ignore[misc]


class ConfigError(CliError):
    exit_code = ExitCode.CONFIG
    category = "configuration"


class AuthError(CliError):
    """There is no usable session: sign-in did not produce one, none is stored, it expired beyond renewal, or the API
    rejected its credentials."""

    exit_code = ExitCode.AUTH_REQUIRED
    category = "authentication"


AuthRequired = AuthError


class NetworkError(CliError):
    exit_code = ExitCode.NETWORK
    category = "network"


class NotTransmitted(Exception):
    """`cause` happened before a refresh token was sent, so the current session can stay."""

    def __init__(self, cause: CliError) -> None:
        super().__init__(cause.message)
        self.cause = cause


class ProtocolError(CliError):
    """A server answered, but not in a form the CLI can trust. Nothing from that answer is kept."""

    exit_code = ExitCode.CONFIG
    category = "protocol"


class StorageError(CliError):
    exit_code = ExitCode.CONFIG
    category = "storage"


class InteractionError(CliError):
    """The local side of an interactive sign-in failed: the callback port is taken or no browser could be opened."""

    exit_code = ExitCode.CONFIG
    category = "interaction"


class UsageError(CliError):
    """A command-line argument names something unusable, such as a file that is not an OMEX archive."""

    exit_code = ExitCode.USAGE
    category = "usage"


class ForbiddenError(CliError):
    """The API refused an authenticated request. Signing in again cannot change that, so it is never retried."""

    exit_code = ExitCode.FORBIDDEN
    category = "forbidden"


Forbidden = ForbiddenError


class RateLimitedError(NetworkError):
    category = "rate_limited"


RateLimited = RateLimitedError


class ApiError(CliError):
    """An unexpected response from compose-api: ``status_code`` and the decoded ``detail``."""

    category = "api_error"

    def __init__(
        self,
        message_or_status: str | int,
        detail: JsonValue = None,
        message: str | None = None,
        *,
        status_code: int | None = None,
    ) -> None:
        if isinstance(message_or_status, int):
            self.status_code = message_or_status
            self.detail = detail
            msg = message or f"compose-api returned {message_or_status}: {detail}"
        else:
            self.status_code = status_code if status_code is not None else 0
            self.detail = detail
            msg = message_or_status
        super().__init__(msg)


ComposeApiError = ApiError


class InvalidRequestError(ApiError):
    """400 or 422. ``violations`` lists the document validation errors when the service reports them."""

    category = "invalid_request"

    @property
    def violations(self) -> list[Any]:
        if isinstance(self.detail, dict):
            v = self.detail.get("violations")
            return list(v) if isinstance(v, list) else []
        return []


BadRequest = InvalidRequestError


class NotFoundError(ApiError):
    """404."""

    category = "not_found"


NotFound = NotFoundError


class ServerError(ApiError):
    """5xx."""

    category = "server_error"


class ServiceUnavailableError(ServerError, NetworkError):
    """502, 503 or 504: the server is there but cannot answer now. A `ServerError` by its status, and a network
    failure by what to do about it (try again later), so its exit code and category are the network ones."""

    exit_code = ExitCode.NETWORK
    category = "network"


class UncertainOutcomeError(CliError):
    """A non-replayable submission failed after it may have reached the server."""

    exit_code = ExitCode.FAILURE
    category = "uncertain"


UncertainOutcome = UncertainOutcomeError


class JobFailedError(CliError):
    """A simulation or build ended in a terminal state other than completed."""

    exit_code = ExitCode.FAILURE
    category = "job_failed"


JobFailed = JobFailedError


class ApiTimeout(CliError, TimeoutError):
    """A wait ran past its deadline. ``last`` is the last state seen, if any."""

    exit_code = ExitCode.WAIT_TIMEOUT
    category = "wait_timeout"

    def __init__(self, message: str, last: object = None) -> None:
        self.last = last
        super().__init__(message)


def detail_of(content: bytes) -> JsonValue:
    """FastAPI's ``detail`` from an error body; the raw text when the body is not JSON."""
    try:
        body: JsonValue = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return content.decode(errors="replace")
    return body.get("detail", body) if isinstance(body, dict) else body


def raise_for(response: Response[Any]) -> None:
    """Raise the typed error for a non-2xx response."""
    code = int(response.status_code)
    if 200 <= code < 300:
        return
    detail = detail_of(response.content)
    if code == 401:
        raise AuthError(f"compose-api rejected the credentials (HTTP 401): {detail}")
    if code == 403:
        raise ForbiddenError(f"compose-api refused the request (HTTP 403): {detail}")
    if code in (400, 422):
        raise BadRequest(code, detail)
    if code == 404:
        raise NotFound(code, detail)
    if code == 429:
        raise RateLimitedError(f"compose-api is rate limiting requests (HTTP 429): {detail}")
    if code >= 500:
        raise ServerError(code, detail)
    raise ComposeApiError(code, detail)
