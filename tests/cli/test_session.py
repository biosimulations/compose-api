"""Security state-machine tests use the real file lock/journal and injected credential/provider boundaries."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr

from compose_api.cli.auth.models import Identity, SessionRecord, TokenGrant
from compose_api.cli.auth.session import AuthSession
from compose_api.cli.auth.state import FileState, SessionState
from compose_api.cli.auth.storage import MemoryCredentialStore
from compose_api.cli.config import requested_scopes
from compose_api.cli.errors import AuthError, NetworkError, NotTransmitted, ProtocolError, StorageError
from tests.fixtures.cli_fixtures import cli_settings

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def grant(issuer: str, *, expires: int = 3600, refresh: str | None = "refresh-canary") -> TokenGrant:
    return TokenGrant(
        identity=Identity(issuer=issuer, subject="auth0|session-test"),
        access_token=SecretStr("access-canary"),
        refresh_token=None if refresh is None else SecretStr(refresh),
        scopes=requested_scopes(persistent=True),
        access_token_expires_at=NOW + timedelta(seconds=expires),
        received_at=NOW,
    )


class Provider:
    def __init__(self, successor: TokenGrant) -> None:
        self.successor = successor
        self.calls = 0
        self.revokes = 0
        self.failure: Exception | None = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def refresh(self, token: SecretStr, scopes: tuple[str, ...]) -> TokenGrant:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        if self.failure:
            raise self.failure
        return self.successor

    async def revoke(self, token: SecretStr) -> None:
        self.revokes += 1
        if self.failure:
            raise self.failure


def setup(tmp_path: Path) -> tuple[AuthSession, MemoryCredentialStore, Provider]:
    settings = cli_settings(callback_port=8400)
    store = MemoryCredentialStore()
    session = AuthSession(
        settings, store, state=FileState(settings.binding_key(persistent=True), tmp_path / "state"), clock=lambda: NOW
    )
    return session, store, Provider(grant(settings.issuer, refresh="successor-canary"))


async def seed(session: AuthSession, *, expires: int = 1, refresh: str | None = "refresh-canary") -> SessionRecord:
    async with session.login_transaction() as snapshot:
        return await session.commit(grant(session.settings.issuer, expires=expires, refresh=refresh), snapshot)


@pytest.mark.asyncio
async def test_two_workers_refresh_once(tmp_path: Path) -> None:
    session, store, provider = setup(tmp_path)
    await seed(session)
    other = AuthSession(
        session.settings, store, state=FileState(session.binding, session.state.root), clock=lambda: NOW
    )
    first, second = await asyncio.gather(session.get_access_token(provider), other.get_access_token(provider))
    assert provider.calls == 1
    assert first == second
    assert first.generation == 2
    assert first.refresh_token == SecretStr("successor-canary")
    for path in session.state.root.iterdir():
        assert b"canary" not in path.read_bytes()
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remaining,status,refreshes",
    [(61, "valid", 0), (60, "near_expiry", 1), (1, "near_expiry", 1), (0, "expired", 1), (-60, "expired", 1)],
)
async def test_expiry_boundaries(tmp_path: Path, remaining: int, status: str, refreshes: int) -> None:
    session, _, provider = setup(tmp_path)
    await seed(session, expires=remaining)
    assert (await session.status()).state == status
    assert provider.calls == 0
    await session.get_access_token(provider)
    assert provider.calls == refreshes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [AuthError("revoked"), AuthError("expired"), NetworkError("ambiguous"), ProtocolError("bad response")]
)
async def test_uncertain_or_refused_rotation_never_replays(tmp_path: Path, failure: Exception) -> None:
    session, store, provider = setup(tmp_path)
    await seed(session)
    provider.failure = failure
    with pytest.raises(type(failure)):
        await session.get_access_token(provider)
    assert store.load(session.binding) is None
    with pytest.raises(AuthError):
        await session.get_access_token(provider)
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_failure_before_the_refresh_token_is_sent_keeps_the_session(tmp_path: Path) -> None:
    session, store, provider = setup(tmp_path)
    saved = await seed(session)
    provider.failure = NotTransmitted(NetworkError("could not reach Auth0"))
    with pytest.raises(NetworkError, match="could not reach Auth0"):
        await session.get_access_token(provider)
    assert store.load(session.binding) == saved
    assert session.state.read().journal is None
    provider.failure = None
    renewed = await session.get_access_token(provider)
    assert renewed.generation == saved.generation + 1
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_missing_rotation_or_changed_identity_invalidates(tmp_path: Path) -> None:
    session, store, provider = setup(tmp_path)
    await seed(session)
    provider.successor = grant(session.settings.issuer, refresh=None)
    with pytest.raises(ProtocolError):
        await session.get_access_token(provider)
    assert store.load(session.binding) is None
    await seed(session)
    provider.successor = grant("https://foreign.example/")
    with pytest.raises(ProtocolError):
        await session.get_access_token(provider)
    assert store.load(session.binding) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("successor_written", [False, True])
async def test_crash_journal_recovery(tmp_path: Path, successor_written: bool) -> None:
    session, store, provider = setup(tmp_path)
    old = await seed(session)
    session.state.write(SessionState(generation=old.generation, active=True, journal="a" * 32))
    if successor_written:
        store.save(
            session.binding,
            SessionRecord.from_grant(provider.successor, binding_key=session.binding, generation=old.generation + 1),
        )
        assert (await session.get_access_token(provider)).generation == 2
    else:
        with pytest.raises(AuthError, match="Interrupted"):
            await session.get_access_token(provider)
        assert store.load(session.binding) is None
    assert provider.calls == 0
    assert session.state.read().journal is None


@pytest.mark.asyncio
async def test_post_rotation_storage_failure_is_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session, store, provider = setup(tmp_path)
    await seed(session)

    def fail(*args: object) -> None:
        raise StorageError("write unavailable")

    monkeypatch.setattr(store, "save", fail)
    with pytest.raises(StorageError):
        await session.get_access_token(provider)
    assert provider.calls == 1
    assert store.load(session.binding) is None
    with pytest.raises(AuthError):
        await session.get_access_token(provider)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["remote", "failed", "local"])
async def test_logout(tmp_path: Path, mode: str) -> None:
    session, store, provider = setup(tmp_path)
    await seed(session)
    if mode == "failed":
        provider.failure = NetworkError("unavailable")
    result = await session.logout(None if mode == "local" else provider)
    assert result.revocation == {"remote": "revoked", "failed": "unavailable", "local": "not_attempted"}[mode]
    assert store.load(session.binding) is None
    assert session.state.read() == SessionState(generation=2)
    assert (await session.status()).state == "missing"
    assert provider.revokes == (mode != "local")
    await session.logout()
    assert session.state.read().generation == 3


@pytest.mark.asyncio
async def test_logout_deletion_failure_leaves_unusable_tombstone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, store, provider = setup(tmp_path)
    await seed(session)

    def fail(binding: str) -> bool:
        raise StorageError("delete failed")

    monkeypatch.setattr(store, "delete", fail)
    with pytest.raises(StorageError):
        await session.logout()
    assert not session.state.read().active
    with pytest.raises(StorageError):
        await session.get_access_token(provider)
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_logout_prevents_late_login_even_when_empty(tmp_path: Path) -> None:
    session, store, _ = setup(tmp_path)
    async with session.login_transaction() as snapshot:
        await session.logout()
        with pytest.raises(AuthError, match="changed"):
            await session.commit(grant(session.settings.issuer), snapshot)
    assert store.load(session.binding) is None


@pytest.mark.asyncio
async def test_logout_serializes_with_refresh(tmp_path: Path) -> None:
    session, store, provider = setup(tmp_path)
    await seed(session)
    provider.release.clear()
    refreshing = asyncio.create_task(session.get_access_token(provider))
    await provider.started.wait()
    logout = asyncio.create_task(session.logout(provider))
    provider.release.set()
    await refreshing
    await logout
    assert store.load(session.binding) is None
    assert not session.state.read().active
    assert provider.revokes == 1


@pytest.mark.asyncio
async def test_refresh_supersedes_late_login(tmp_path: Path) -> None:
    session, store, provider = setup(tmp_path)
    await seed(session)
    async with session.login_transaction() as snapshot:
        refreshed = await session.get_access_token(provider)
        with pytest.raises(AuthError):
            await session.commit(grant(session.settings.issuer), snapshot)
    assert store.load(session.binding) == refreshed


@pytest.mark.asyncio
async def test_cancelled_rotation_invalidates(tmp_path: Path) -> None:
    session, store, provider = setup(tmp_path)
    await seed(session)
    provider.release.clear()
    task = asyncio.create_task(session.get_access_token(provider))
    await provider.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.load(session.binding) is None
    assert not session.state.read().active


@pytest.mark.asyncio
async def test_cancelled_login_preserves_previous_and_releases_lock(tmp_path: Path) -> None:
    session, store, _ = setup(tmp_path)
    old = await seed(session)
    with pytest.raises(asyncio.CancelledError):
        async with session.login_transaction():
            raise asyncio.CancelledError
    assert store.load(session.binding) == old
    async with session.login_transaction():
        pass


@pytest.mark.asyncio
async def test_simultaneous_login_rejected(tmp_path: Path) -> None:
    session, _, _ = setup(tmp_path)
    async with session.login_transaction():
        with pytest.raises(StorageError, match="busy"):
            async with session.login_transaction():
                pass


@pytest.mark.asyncio
async def test_missing_refresh_requires_login(tmp_path: Path) -> None:
    session, _, provider = setup(tmp_path)
    await seed(session, refresh=None)
    with pytest.raises(AuthError):
        await session.get_access_token(provider)
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_changed_profile_isolation(tmp_path: Path) -> None:
    session, store, provider = setup(tmp_path)
    old = await seed(session)
    settings = session.settings.model_copy(update={"api_base_url": "https://other.example"})
    other = AuthSession(settings, store, state=FileState(settings.binding_key(persistent=True), session.state.root))
    assert (await other.status()).state == "missing"
    await other.logout()
    assert store.load(session.binding) == old
    assert provider.calls == 0


# Child processes share credentials only in a manager's memory, never in a plaintext test credential file.
def process_worker(root: str, entries: object, counters: object, barrier: object, stage: str) -> None:
    import os
    from typing import Any, cast

    shared = cast(Any, entries)
    counts = cast(Any, counters)
    sync = cast(Any, barrier)
    settings = cli_settings(callback_port=8400)

    class SharedStore:
        def load(self, key: str) -> SessionRecord | None:
            return cast(SessionRecord | None, shared.get(key))

        def save(self, key: str, record: SessionRecord) -> None:
            if stage == "before_write":
                os._exit(23)
            shared[key] = record
            if stage == "after_write":
                os._exit(23)

        def delete(self, key: str) -> bool:
            return shared.pop(key, None) is not None

    class SharedProvider(Provider):
        async def refresh(self, token: SecretStr, scopes: tuple[str, ...]) -> TokenGrant:
            if stage == "before_rotation":
                os._exit(23)
            counts["refresh"] = counts.get("refresh", 0) + 1
            if stage == "after_rotation":
                os._exit(23)
            return self.successor

    session = AuthSession(
        settings, SharedStore(), state=FileState(settings.binding_key(persistent=True), Path(root)), clock=lambda: NOW
    )
    sync.wait(timeout=15)
    asyncio.run(session.get_access_token(SharedProvider(grant(settings.issuer, refresh="successor-canary"))))


def test_subprocesses_serialize_real_lock(tmp_path: Path) -> None:
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    settings = cli_settings(callback_port=8400)
    binding = settings.binding_key(persistent=True)
    state = FileState(binding, tmp_path / "state")
    state.write(SessionState(generation=1, active=True))
    with context.Manager() as manager:
        entries = manager.dict({
            binding: SessionRecord.from_grant(grant(settings.issuer, expires=0), binding_key=binding, generation=1)
        })
        counters = manager.dict()
        barrier = context.Barrier(3)
        workers = [
            context.Process(target=process_worker, args=(str(state.root), entries, counters, barrier, "normal"))
            for _ in range(2)
        ]
        for worker in workers:
            worker.start()
        barrier.wait(timeout=15)
        for worker in workers:
            worker.join(timeout=20)
            assert not worker.is_alive()
            assert worker.exitcode == 0
        assert counters["refresh"] == 1
        assert entries[binding].generation == 2
        assert entries[binding].refresh_token == SecretStr("successor-canary")


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["before_rotation", "after_rotation", "before_write", "after_write"])
async def test_process_death_recovers_without_replay(tmp_path: Path, stage: str) -> None:
    import multiprocessing

    session, store, provider = setup(tmp_path)
    old = await seed(session)
    context = multiprocessing.get_context("spawn")
    with context.Manager() as manager:
        entries = manager.dict({session.binding: old})
        counters = manager.dict()
        barrier = context.Barrier(2)
        worker = context.Process(
            target=process_worker, args=(str(session.state.root), entries, counters, barrier, stage)
        )
        worker.start()
        barrier.wait(timeout=15)
        worker.join(timeout=20)
        assert worker.exitcode == 23
        store.save(session.binding, entries[session.binding])
        if stage == "after_write":
            assert (await session.get_access_token(provider)).generation == 2
        else:
            with pytest.raises(AuthError):
                await session.get_access_token(provider)
            assert store.load(session.binding) is None
        assert provider.calls == 0
        assert counters.get("refresh", 0) == (stage != "before_rotation")


@pytest.mark.asyncio
async def test_corrupt_metadata_logout_removes_credentials(tmp_path: Path) -> None:
    session, store, _ = setup(tmp_path)
    await seed(session)
    session.state.path.write_text("corrupt")
    await session.logout()
    assert store.load(session.binding) is None
    assert not session.state.read().active


@pytest.mark.asyncio
async def test_provider_unexpected_failure_redacted(tmp_path: Path) -> None:
    session, store, provider = setup(tmp_path)
    await seed(session)
    provider.failure = ValueError("SECRET-PROVIDER-BODY")
    with pytest.raises(ProtocolError) as caught:
        await session.get_access_token(provider)
    assert "SECRET" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert store.load(session.binding) is None
    await seed(session)
    assert (await session.logout(provider)).revocation == "unavailable"


@pytest.mark.asyncio
async def test_journal_write_failure_prevents_provider_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session, store, provider = setup(tmp_path)
    old = await seed(session)

    def fail(value: SessionState) -> None:
        raise StorageError("metadata unavailable")

    monkeypatch.setattr(session.state, "write", fail)
    with pytest.raises(StorageError):
        await session.get_access_token(provider)
    assert provider.calls == 0
    assert store.load(session.binding) == old


@pytest.mark.asyncio
async def test_final_metadata_failure_and_deletion_failure_cannot_reuse_old_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, store, provider = setup(tmp_path)
    await seed(session)
    write = session.state.write

    def fail_successor(value: SessionState) -> None:
        if value.generation == 2 and value.active:
            raise StorageError("metadata unavailable")
        write(value)

    def fail_delete(key: str) -> bool:
        raise StorageError("deletion unavailable")

    monkeypatch.setattr(session.state, "write", fail_successor)
    monkeypatch.setattr(store, "delete", fail_delete)
    with pytest.raises(StorageError):
        await session.get_access_token(provider)
    with pytest.raises(StorageError):
        await session.get_access_token(provider)
    assert provider.calls == 1
    assert not session.state.read().active


@pytest.mark.asyncio
async def test_login_write_failure_cannot_resurrect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session, store, _ = setup(tmp_path)
    save = store.save

    def ambiguous_write(key: str, value: SessionRecord) -> None:
        save(key, value)
        raise StorageError("write verification failed")

    monkeypatch.setattr(store, "save", ambiguous_write)
    with pytest.raises(StorageError):
        await seed(session)
    assert (await session.status()).state == "missing"
    assert store.load(session.binding) is None


@pytest.mark.asyncio
async def test_session_refresh_uses_real_signed_provider_validation(tmp_path: Path, fake_tenant: object) -> None:
    from typing import cast

    from compose_api.cli.auth.oauth import Auth0OAuthClient
    from tests.fixtures.cli_fixtures import FakeTenant

    tenant = cast(FakeTenant, fake_tenant)
    settings = cli_settings(callback_port=8400)
    store = MemoryCredentialStore()
    session = AuthSession(settings, store, state=FileState(settings.binding_key(persistent=True), tmp_path / "state"))
    tenant.queue(
        tenant.TOKEN,
        tenant.token_response(refresh_token="signed-successor", include_id_token=False),  # noqa: S106 -- synthetic credential
    )
    async with Auth0OAuthClient(settings, transport=tenant.transport) as client:
        initial = await client.accept_device_grant(tenant.token_response(), requested_scopes(persistent=True))
        async with session.login_transaction() as snapshot:
            old = await session.commit(initial, snapshot)
        new = await session.get_access_token(client, rejected_generation=old.generation)
        assert new.generation == old.generation + 1
        assert new.identity == old.identity
        assert new.refresh_token == SecretStr("signed-successor")
        tenant.queue(tenant.REVOKE, {})
        assert (await session.logout(client)).revocation == "revoked"
    assert len(tenant.forms(tenant.TOKEN)) == 1
    assert len(tenant.forms(tenant.REVOKE)) == 1
