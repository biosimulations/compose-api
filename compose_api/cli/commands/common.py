"""What the network commands share: what they talk to, and the single `asyncio.run` boundary each one crosses."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import httpx

from compose_api.cli.auth import storage
from compose_api.cli.auth.browser import BrowserLauncher, open_system_browser
from compose_api.cli.auth.storage import CredentialStore
from compose_api.cli.config import CliSettings
from compose_api.cli.output import quiet_http_logging

type StoreFactory = Callable[[CliSettings], CredentialStore]


@dataclass(frozen=True)
class Wiring:
    """What a command talks to. The CLI leaves every field unset; tests replace one to stand in for it."""

    store_factory: StoreFactory | None = None  # unset: the OS credential store
    launcher: BrowserLauncher | None = None  # unset: the system browser
    auth0_transport: httpx.AsyncBaseTransport | None = None
    api_transport: httpx.AsyncBaseTransport | None = None

    def store(self, settings: CliSettings, *, writable: bool, check: bool = True) -> CredentialStore:
        """The persistent store. `writable` probes it with a throwaway write, for commands about to sign in;
        `check=False` skips reading the stored record, so logout can erase one too corrupt to parse."""
        if self.store_factory is not None:
            return self.store_factory(settings)
        return storage.open_persistent_store(settings, check=check, writable=writable)

    def browser(self) -> BrowserLauncher:
        return self.launcher or open_system_browser


def run[T](work: Coroutine[Any, Any, T]) -> T:
    """Run a command's network work. httpx's request logging is silenced for the duration."""
    with quiet_http_logging():
        return asyncio.run(work)
