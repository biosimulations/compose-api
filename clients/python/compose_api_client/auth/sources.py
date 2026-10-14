"""Adapters bridging `AuthSession` / `SessionRecord` (`[auth]` extra) to `ext/credentials.py`'s `Credential`."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeVar

import httpx

from compose_api_client.auth.models import SessionRecord
from compose_api_client.auth.oauth import Auth0OAuthClient
from compose_api_client.auth.session import AuthSession, OAuthSessionClient
from compose_api_client.ext.credentials import Credential
from compose_api_client.ext.errors import AuthError
from compose_api_client.profiles import CliSettings

T = TypeVar("T")


def _to_credential(record: SessionRecord) -> Credential:
    return Credential(
        access_token=record.access_token.get_secret_value(),
        generation=record.generation,
        issuer=record.identity.issuer,
        subject=record.identity.subject,
    )


class AsyncStoredSession:
    """Asynchronous persistent session adapter for `AsyncComposeSession` and `ComposeApi`."""

    def __init__(
        self,
        session: AuthSession,
        oauth: OAuthSessionClient,
        *,
        required: bool = True,
        records: dict[int, SessionRecord] | None = None,
    ) -> None:
        self.session = session
        self.oauth = oauth
        self.required = required
        # The records handed out, by generation; `SyncStoredSession` shares one dict across its per-call instances.
        self._records: dict[int, SessionRecord] = {} if records is None else records

    async def current_record(self) -> SessionRecord:
        record = await self.session.get_access_token(self.oauth)
        self._records[record.generation] = record
        return record

    async def renew_record(self, rejected: SessionRecord) -> SessionRecord | None:
        if rejected.refresh_token is None:
            return None
        record = await self.session.get_access_token(self.oauth, rejected_generation=rejected.generation)
        self._records[record.generation] = record
        return record

    async def current(self) -> Credential | None:
        if not self.required:
            status = await self.session.status()
            if status.state == "missing":
                return None
        record = await self.current_record()
        return _to_credential(record)

    async def renew(self, rejected: Credential) -> Credential | None:
        if rejected.generation is None:
            return None
        prior = self._records.get(rejected.generation)
        if prior is not None and prior.refresh_token is None:
            return None
        try:
            record = await self.session.get_access_token(self.oauth, rejected_generation=rejected.generation)
        except AuthError:
            if prior is not None and prior.refresh_token is None:
                return None
            raise
        self._records[record.generation] = record
        return _to_credential(record)

    async def confirmed(self, credential: Credential | SessionRecord, at: datetime) -> None:
        if isinstance(credential, SessionRecord):
            await self.session.mark_verified(credential, at)
            return
        if credential.generation is None:
            return
        record = self._records.get(credential.generation)
        if record is not None:
            await self.session.mark_verified(record, at)


class StoredSession:
    """Persistent session adapter for both sync `ComposeSession` and async `ComposeApi`."""

    def __init__(self, session: AuthSession, oauth: OAuthSessionClient, *, required: bool = True) -> None:
        self.session = session
        self.oauth = oauth
        self.required = required
        self._async = AsyncStoredSession(session, oauth, required=required)

    async def current(self) -> SessionRecord:
        return await self._async.current_record()

    async def renew(self, rejected: SessionRecord) -> SessionRecord | None:
        return await self._async.renew_record(rejected)

    async def confirmed(self, record: SessionRecord, at: datetime) -> None:
        await self.session.mark_verified(record, at)

    def as_async_source(self) -> AsyncStoredSession:
        return self._async


class SyncStoredSession:
    """A profile's stored session as a sync `TokenSource`, for the `ComposeSession` every CLI command uses.

    Optional: no stored session means an anonymous call (`current()` is None), as the API allows. Each call runs on
    its own event loop, so the Auth0 client a renewal needs is opened inside that loop and closed before it ends; one
    client shared across loops would be bound to the first.
    """

    def __init__(
        self, settings: CliSettings, session: AuthSession, *, auth0_transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self.session = session
        self.auth0_transport = auth0_transport
        self._records: dict[int, SessionRecord] = {}

    def _run(self, work: Callable[[AsyncStoredSession], Awaitable[T]]) -> T:
        async def within_one_loop() -> T:
            async with Auth0OAuthClient(self.settings, transport=self.auth0_transport) as oauth:
                return await work(AsyncStoredSession(self.session, oauth, required=False, records=self._records))

        return asyncio.run(within_one_loop())

    def current(self) -> Credential | None:
        return self._run(lambda stored: stored.current())

    def renew(self, rejected: Credential) -> Credential | None:
        return self._run(lambda stored: stored.renew(rejected))

    def confirmed(self, credential: Credential, at: datetime) -> None:
        self._run(lambda stored: stored.confirmed(credential, at))


class OneCommandSession:
    """A `--ephemeral-auth` session: memory only, no refresh token, nothing recorded anywhere."""

    def __init__(self, record: SessionRecord) -> None:
        self.record = record
        self._credential = _to_credential(record)

    async def current(self) -> SessionRecord:
        return self.record

    async def renew(self, rejected: SessionRecord) -> SessionRecord | None:
        return None

    async def confirmed(self, record: SessionRecord, at: datetime) -> None:
        return None

    def as_sync_source(self) -> _SyncOneCommandSource:
        return _SyncOneCommandSource(self._credential)

    def as_async_source(self) -> _AsyncOneCommandSource:
        return _AsyncOneCommandSource(self._credential)


class _SyncOneCommandSource:
    def __init__(self, credential: Credential) -> None:
        self._credential = credential

    def current(self) -> Credential | None:
        return self._credential

    def renew(self, rejected: Credential) -> Credential | None:
        return None

    def confirmed(self, credential: Credential, at: datetime) -> None:
        return None


class _AsyncOneCommandSource:
    def __init__(self, credential: Credential) -> None:
        self._credential = credential

    async def current(self) -> Credential | None:
        return self._credential

    async def renew(self, rejected: Credential) -> Credential | None:
        return None

    async def confirmed(self, credential: Credential, at: datetime) -> None:
        return None
