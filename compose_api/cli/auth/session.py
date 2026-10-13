"""Session mutations serialized by binding; uncertain refresh credentials are never replayed."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, SecretStr

from compose_api.cli.auth.models import Identity, SessionRecord, TokenGrant
from compose_api.cli.auth.state import FileState, MemoryState, SessionState
from compose_api.cli.auth.storage import CredentialStore, MemoryCredentialStore, validate_record
from compose_api.cli.config import CliSettings
from compose_api.cli.errors import AuthError, CliError, NotTransmitted, ProtocolError, StorageError


class OAuthSessionClient(Protocol):
    async def refresh(self, refresh_token: SecretStr, scopes: tuple[str, ...]) -> TokenGrant: ...
    async def revoke(self, refresh_token: SecretStr) -> None: ...


class AuthStatus(BaseModel):
    profile: str
    api_base_url: str
    state: str
    identity: Identity | None = None
    expires_at: datetime | None = None
    renewable: bool = False
    api_verified_at: datetime | None = None


class LogoutResult(BaseModel):
    local_cleared: bool = True
    revocation: str


class AuthSession:
    def __init__(
        self,
        settings: CliSettings,
        store: CredentialStore,
        *,
        state: FileState | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.binding = settings.binding_key(persistent=True)
        self.store = store
        if state is None and isinstance(store, MemoryCredentialStore):
            existing = store.load(self.binding)
            initial = SessionState(generation=existing.generation, active=True) if existing else SessionState()
            state = store.states.setdefault(self.binding, MemoryState(initial))
        self.state = state if state is not None else FileState(self.binding)
        self.clock = clock

    def _invalidate(self, state: SessionState) -> None:
        # Durable tombstone first: deletion failure must not make the credential reusable.
        self.state.write(SessionState(generation=state.generation + 1))
        self.store.delete(self.binding)

    def _read(self) -> tuple[SessionState, SessionRecord | None]:
        state = self.state.read()
        record = self.store.load(self.binding)
        if record is not None:
            validate_record(self.binding, record)
            if record.identity.issuer != self.settings.issuer:
                raise StorageError("Credential issuer does not match this profile")
        if state.journal is not None:
            if record is not None and record.generation == state.generation + 1:
                # The complete successor was persisted; only final metadata cleanup was interrupted.
                state = SessionState(generation=record.generation, active=True)
                self.state.write(state)
            else:
                self._invalidate(state)
                raise AuthError("Interrupted session renewal or replacement; sign in again")
        if record is None:
            if state.active:
                self._invalidate(state)
                state = self.state.read()
            return state, None
        if not state.active or record.generation != state.generation:
            self._invalidate(state)
            raise AuthError("Stale credential state was discarded; sign in again")
        return state, record

    @asynccontextmanager
    async def login_transaction(self) -> AsyncIterator[int]:
        async with self.state.lock(login=True):
            async with self.state.lock():
                # Recovery may require login, but a new login is itself a safe recovery operation.
                try:
                    state, _ = self._read()
                except AuthError:
                    state = self.state.read()
                snapshot = state.generation
            yield snapshot

    async def commit(self, grant: TokenGrant, snapshot: int) -> SessionRecord:
        async with self.state.lock():
            state = self.state.read()
            if state.generation != snapshot or state.journal is not None:
                raise AuthError("Session changed while signing in; the late sign-in was discarded")
            if grant.identity.issuer != self.settings.issuer:
                raise ProtocolError("Sign-in issuer does not match this profile")
            try:
                return self._replace(state, grant)
            except BaseException:
                self._invalidate(state)
                raise

    def _replace(
        self, state: SessionState, grant: TokenGrant, *, api_verified_at: datetime | None = None
    ) -> SessionRecord:
        record = SessionRecord.from_grant(grant, binding_key=self.binding, generation=state.generation + 1)
        if api_verified_at is not None:
            record = record.model_copy(update={"api_verified_at": api_verified_at})
        validate_record(self.binding, record)
        self.state.write(state.model_copy(update={"journal": uuid.uuid4().hex}))
        # On write failure the journal MUST remain. Even a backend error may have stored the whole successor.
        self.store.save(self.binding, record)
        self.state.write(SessionState(generation=record.generation, active=True))
        return record

    async def mark_verified(self, record: SessionRecord, at: datetime) -> SessionRecord | None:
        """Record that the API confirmed `record`'s identity at `at`. A session replaced meanwhile is left alone.

        The credential itself does not change, so this is an ordinary whole-record write without a journal: an
        interrupted write leaves either the old or the new copy of the same generation, and both are valid.
        """
        async with self.state.lock():
            _, current = self._read()
            if current is None or current.generation != record.generation or current.identity != record.identity:
                return None
            updated = current.model_copy(update={"api_verified_at": at})
            self.store.save(self.binding, updated)
            return updated

    async def status(self) -> AuthStatus:
        async with self.state.lock():
            _, record = self._read()
            result = AuthStatus(profile=self.settings.profile, api_base_url=self.settings.api_base_url, state="missing")
            if record is None:
                return result
            remaining = (record.access_token_expires_at - self.clock()).total_seconds()
            return result.model_copy(
                update={
                    "state": "expired" if remaining <= 0 else "near_expiry" if remaining <= 60 else "valid",
                    "identity": record.identity,
                    "expires_at": record.access_token_expires_at,
                    "renewable": record.refresh_token is not None,
                    "api_verified_at": record.api_verified_at,
                }
            )

    async def get_access_token(
        self,
        client: OAuthSessionClient,
        *,
        rejected_generation: int | None = None,
    ) -> SessionRecord:
        """Return validated session metadata plus bearer; a rejected generation forces at most one renewal."""
        async with self.state.lock():
            state, record = self._read()
            if record is None:
                raise AuthError("No session for this profile; sign in first")
            forced = rejected_generation is not None and record.generation == rejected_generation
            if not forced and record.access_token_expires_at > self.clock() + timedelta(seconds=60):
                return record
            if record.refresh_token is None:
                raise AuthError("Session needs renewal but has no refresh credential; sign in again")
            self.state.write(state.model_copy(update={"journal": uuid.uuid4().hex}))
            try:
                grant = await client.refresh(record.refresh_token, record.scopes)
                self._validate_successor(record, grant)
                return self._replace(state, grant, api_verified_at=record.api_verified_at)
            except NotTransmitted as exc:
                # The refresh token never left the process, so the journal is a false alarm.
                try:
                    self.state.write(state)
                except StorageError:
                    self._invalidate(state)
                raise exc.cause from None
            except BaseException as exc:
                # Includes task cancellation/KeyboardInterrupt. No retry of a possibly spent credential.
                # If durable cleanup fails, the in-flight journal still blocks the original credential.
                self._invalidate(state)
                if isinstance(exc, Exception) and not isinstance(exc, CliError):
                    raise ProtocolError("Session renewal failed; sign in again") from None
                raise

    def _validate_successor(self, record: SessionRecord, grant: TokenGrant) -> None:
        if grant.identity != record.identity or grant.refresh_token is None:
            raise ProtocolError("Renewal changed identity or omitted the rotated credential; sign in again")
        if grant.access_token_expires_at <= self.clock() + timedelta(seconds=60):
            raise ProtocolError("Renewed token expires too soon; check the system clock and sign in again")

    async def logout(self, client: OAuthSessionClient | None = None) -> LogoutResult:
        async with self.state.lock():
            try:
                state = self.state.read()
            except StorageError:
                # Unknown generation: a fresh non-secret epoch invalidates any outstanding login snapshot.
                # write() still enforces ownership/mode before replacing corrupt metadata.
                state = SessionState(generation=uuid.uuid4().int)
            record = None
            with suppress(StorageError):
                record = self.store.load(self.binding)
            result = "not_attempted"
            try:
                if client is not None and record is not None and record.refresh_token is not None:
                    try:
                        await client.revoke(record.refresh_token)
                        result = "revoked"
                    except Exception:
                        # Revocation is best-effort; provider detail is never displayed or retained.
                        result = "unavailable"
            finally:
                self._invalidate(state)
            return LogoutResult(revocation=result)

    async def authenticate(self, operation: Callable[[], Awaitable[TokenGrant]]) -> SessionRecord:
        async with self.login_transaction() as snapshot:
            grant = await operation()
            return await self.commit(grant, snapshot)
