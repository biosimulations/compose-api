"""Exit codes and the errors the CLI reports to its user.

A `CliError` message is printed verbatim, so it must already be safe to show: it names settings, sources and rules,
never a configured value, a token or a server response body.
"""

from enum import IntEnum
from typing import ClassVar


class ExitCode(IntEnum):
    """The process exit status contract. Scripts depend on these values; never renumber one."""

    OK = 0
    FAILURE = 1  # an unsuccessful API response or command outcome not covered below
    USAGE = 2  # argparse's own status for a malformed command line
    AUTH_REQUIRED = 3
    FORBIDDEN = 4
    NETWORK = 5
    CONFIG = 6  # configuration, credential storage or protocol errors
    CANCELLED = 130


class CliError(Exception):
    """An expected failure with a message that is safe to print."""

    exit_code: ClassVar[ExitCode] = ExitCode.FAILURE
    category: ClassVar[str] = "failure"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConfigError(CliError):
    exit_code = ExitCode.CONFIG
    category = "configuration"


class AuthError(CliError):
    """There is no usable session: sign-in did not produce one, none is stored, it expired beyond renewal, or the API
    rejected its credentials."""

    exit_code = ExitCode.AUTH_REQUIRED
    category = "authentication"


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


class RateLimitedError(NetworkError):
    category = "rate_limited"


# Unsuccessful API answers that are neither authentication, authorization nor transport problems: exit 1, each with
# its own category so scripts can tell them apart without parsing messages.
class NotFoundError(CliError):
    category = "not_found"


class InvalidRequestError(CliError):
    category = "invalid_request"


class ServerError(CliError):
    category = "server_error"


class ApiError(CliError):
    category = "api_error"
