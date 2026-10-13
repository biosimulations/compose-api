"""Dependency-free credential boundary for `compose_api_client.ext`.

`ext/` ships in the base `compose-api-client` package (`attrs`, `httpx`, `python-dateutil`) and must never import
`pydantic`, `keyring`, `authlib`, `jwt`, `portalocker` or `compose_api_client.auth`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Protocol

from compose_api_client.ext.errors import UsageError

TOKEN_ENV_VAR: Final = "COMPOSE_API_TOKEN"  # noqa: S105 -- environment variable name, not a secret


@dataclass(frozen=True)
class Credential:
    """One bearer to send. `generation` names the stored-session record it came from; None for a static token."""

    access_token: str = field(repr=False)
    generation: int | None = None
    issuer: str | None = None
    subject: str | None = None


class TokenSource(Protocol):
    """Synchronous credential source for `ComposeSession`."""

    def current(self) -> Credential | None: ...  # None: send the request anonymously
    def renew(self, rejected: Credential) -> Credential | None: ...  # None: this source cannot renew
    def confirmed(self, credential: Credential, at: datetime) -> None: ...


class AsyncTokenSource(Protocol):
    """Asynchronous credential source for `AsyncComposeSession`."""

    async def current(self) -> Credential | None: ...
    async def renew(self, rejected: Credential) -> Credential | None: ...
    async def confirmed(self, credential: Credential, at: datetime) -> None: ...


class EnvironmentToken:
    """Static bearer read from `COMPOSE_API_TOKEN`. Never renewed and never printed."""

    def __init__(self, token: str | None = None) -> None:
        raw = os.environ.get(TOKEN_ENV_VAR) if token is None else token
        if raw is None or not raw.strip():
            raise UsageError(f"{TOKEN_ENV_VAR} must not be empty; unset it or set a valid access token")
        self._credential = Credential(access_token=raw.strip(), generation=None)

    def current(self) -> Credential | None:
        return self._credential

    def renew(self, rejected: Credential) -> Credential | None:
        return None

    def confirmed(self, credential: Credential, at: datetime) -> None:
        return None

    async def async_current(self) -> Credential | None:
        return self._credential

    async def async_renew(self, rejected: Credential) -> Credential | None:
        return None

    async def async_confirmed(self, credential: Credential, at: datetime) -> None:
        return None

    def as_async(self) -> _AsyncEnvironmentToken:
        return _AsyncEnvironmentToken(self._credential)


class _AsyncEnvironmentToken:
    def __init__(self, credential: Credential) -> None:
        self._credential = credential

    async def current(self) -> Credential | None:
        return self._credential

    async def renew(self, rejected: Credential) -> Credential | None:
        return None

    async def confirmed(self, credential: Credential, at: datetime) -> None:
        return None


class StaticToken:
    """Wraps a static `token=` string passed to `ComposeSession` / `AsyncComposeSession`."""

    def __init__(self, token: str) -> None:
        if not token or not token.strip():
            raise UsageError("token must not be empty")
        self._credential = Credential(access_token=token.strip(), generation=None)

    def current(self) -> Credential | None:
        return self._credential

    def renew(self, rejected: Credential) -> Credential | None:
        return None

    def confirmed(self, credential: Credential, at: datetime) -> None:
        return None

    def as_async(self) -> _AsyncEnvironmentToken:
        return _AsyncEnvironmentToken(self._credential)
