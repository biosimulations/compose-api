"""The application layer over the generated client (docs/plan-cli.md, step B2): sessions, waiting, downloads and
typed errors. Hand-written; `make clients` leaves this package alone."""

from compose_api_client.ext.errors import ApiTimeout, BadRequest, ComposeApiError, NotFound, ServerError
from compose_api_client.ext.session import (
    DEFAULT_URL,
    SUBMITTING,
    TERMINAL,
    AsyncComposeSession,
    ComposeSession,
    FileSource,
    JobState,
)

__all__ = [
    "DEFAULT_URL",
    "SUBMITTING",
    "TERMINAL",
    "ApiTimeout",
    "AsyncComposeSession",
    "BadRequest",
    "ComposeApiError",
    "ComposeSession",
    "FileSource",
    "JobState",
    "NotFound",
    "ServerError",
]
