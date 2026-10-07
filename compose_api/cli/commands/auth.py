"""`auth signup` and `auth login`."""

import argparse
import asyncio
import logging
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx

from compose_api.cli.auth.browser import BrowserLauncher, open_system_browser
from compose_api.cli.auth.models import Provider, SignInRequest
from compose_api.cli.auth.signin import connection_for, persistent_sign_in
from compose_api.cli.auth.storage import CredentialStore, open_persistent_store
from compose_api.cli.config import CliSettings, load_cli_settings
from compose_api.cli.errors import CommandUnavailableError

type StoreFactory = Callable[[CliSettings], CredentialStore]


def signup(args: argparse.Namespace) -> int:
    return sign_in_command(args, signup=True)


def login(args: argparse.Namespace) -> int:
    return sign_in_command(args, signup=False)


def sign_in_command(
    args: argparse.Namespace,
    *,
    signup: bool,
    store_factory: StoreFactory = open_persistent_store,
    launcher: BrowserLauncher = open_system_browser,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    settings = load_cli_settings(args.profile).settings
    request = SignInRequest(
        signup=signup,
        provider=None if args.provider is None else Provider(args.provider),
        device=args.device,
        open_browser=not args.no_browser,
        persistent=True,
    )
    # Everything that can be wrong locally is found before any network request or browser window: the profile, the
    # provider's connection, and somewhere to keep the session.
    settings.require_client_id()
    connection_for(settings, request)
    store = store_factory(settings)
    with _quiet_http_logging():
        record = asyncio.run(
            persistent_sign_in(settings, request, store, notify=notify, launcher=launcher, transport=transport)
        )
    notify(
        f"Signed in to profile {settings.profile!r} as {printable(record.identity.subject)}"
        f" ({printable(record.identity.issuer)})."
    )
    if record.refresh_token is None:
        notify(
            "Auth0 issued no refresh token, so this session cannot be renewed: sign in again after"
            f" {record.access_token_expires_at:%Y-%m-%d %H:%M} UTC."
        )
    raise CommandUnavailableError(
        "the session was saved, but this build cannot yet confirm it with the Compose API, so treat it as unverified"
    )


def notify(message: str) -> None:
    """Progress and instructions go to stderr, keeping stdout for results."""
    print(message, file=sys.stderr)


def printable(text: str) -> str:
    """`text` with anything that could drive the terminal escaped."""
    return text if text.isprintable() else text.encode("unicode_escape").decode("ascii")


@contextmanager
def _quiet_http_logging() -> Iterator[None]:
    """httpx logs every request at INFO and httpcore traces at DEBUG; neither belongs in a sign-in's output."""
    loggers = [logging.getLogger(name) for name in ("httpx", "httpcore")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        for logger, level in zip(loggers, levels, strict=True):
            logger.setLevel(level)
