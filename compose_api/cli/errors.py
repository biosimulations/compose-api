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


class CommandUnavailableError(CliError):
    """The command is part of the CLI surface but this build cannot carry it out yet."""

    category = "unavailable"
