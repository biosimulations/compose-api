"""How the CLI writes to the terminal: results to stdout, progress and errors to stderr, nothing that can drive it.

Text that came from outside the CLI -- an identity, a file name, a field the API returned -- passes through
`printable` before it is shown, so control characters cannot move the cursor, recolour the terminal or hide output.
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

MAX_FIELD_CHARS: Final = 500


def printable(text: str, *, limit: int = MAX_FIELD_CHARS) -> str:
    """`text` with control characters escaped, cut to `limit` characters."""
    shown = text if text.isprintable() else text.encode("unicode_escape").decode("ascii")
    return shown if len(shown) <= limit else f"{shown[: limit - 1]}…"


def printable_lines(text: str) -> str:
    """Like `printable`, but keeps line breaks: for the CLI's own multi-line messages."""
    return "\n".join(printable(line, limit=10 * MAX_FIELD_CHARS) for line in text.split("\n"))


def notify(message: str) -> None:
    """Progress and instructions go to stderr, keeping stdout for results."""
    print(message, file=sys.stderr)


def emit(text: str) -> None:
    print(text)


def emit_json(document: Any) -> None:
    """One JSON document on stdout. Non-ASCII is escaped, so the output is safe to show as well as to parse."""
    print(json.dumps(document, ensure_ascii=True, default=str))


@contextmanager
def quiet_http_logging() -> Iterator[None]:
    """httpx logs every request at INFO and httpcore traces at DEBUG; neither belongs in a command's output."""
    loggers = [logging.getLogger(name) for name in ("httpx", "httpcore")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        for logger, level in zip(loggers, levels, strict=True):
            logger.setLevel(level)
