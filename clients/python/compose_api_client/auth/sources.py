"""Adapters bridging `AuthSession` / `SessionRecord` (`[auth]` extra) to `ext/credentials.py`'s `Credential`."""

from __future__ import annotations

import asyncio
from datetime import datetime

from compose_api_client.auth.models import SessionRecord
from compose_api_client.auth.session import AuthSession, OAuthSessionClient
from compose_api_client.ext.credentials import Credential
from compose_api_client.ext.errors import AuthError


def _to_credential(record: SessionRecord) -> Credential:
    return Credential(
        access_token=record.access_token.get_secret_value(),
        generation=record.generation,
        issuer=record.identity.issuer,
        subject=record.identity.subject,
    )


class AsyncStoredSession:
    """Asynchronous persistent session adapter for `AsyncComposeSession` and `ComposeApi`."""

    def __init__(self, session: AuthSession, oauth: OAuthSessionClient, *, required: bool = True) -> None:
        self.session = session
        self.oauth = oauth
        self.required = required
        self._records: dict[int, SessionRecord] = {}

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

    def sync_current(self) -> Credential | None:
        return asyncio.run(self._async.current())

    def sync_renew(self, rejected: Credential) -> Credential | None:
        return asyncio.run(self._async.renew(rejected))

    def sync_confirmed(self, credential: Credential, at: datetime) -> None:
        asyncio.run(self._async.confirmed(credential, at))

    def as_sync_source(self) -> _SyncStoredSessionSource:
        return _SyncStoredSessionSource(self._async)

    def as_async_source(self) -> AsyncStoredSession:
        return self._async


class _SyncStoredSessionSource:
    def __init__(self, inner: AsyncStoredSession) -> None:
        self._inner = inner

    def current(self) -> Credential | None:
        return asyncio.run(self._inner.current())

    def renew(self, rejected: Credential) -> Credential | None:
        return asyncio.run(self._inner.renew(rejected))

    def confirmed(self, credential: Credential, at: datetime) -> None:
        asyncio.run(self._inner.confirmed(credential, at))


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
