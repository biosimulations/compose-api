"""OS backend contract without touching the developer's keychain."""

import json
from pathlib import Path

import pytest
from keyring.backends import macOS
from keyring.backends.fail import Keyring as FailKeyring
from keyring.errors import KeyringLocked

from compose_api.cli.auth.models import SessionRecord
from compose_api.cli.auth.state import FileState, SessionState
from compose_api.cli.auth.storage import MAX_RECORD_BYTES, SERVICE, KeyringCredentialStore
from compose_api.cli.errors import StorageError
from tests.cli.test_session import grant
from tests.fixtures.cli_fixtures import cli_settings


def backend(monkeypatch: pytest.MonkeyPatch) -> tuple[KeyringCredentialStore, dict[str, str]]:
    """Patch only the OS calls on a genuine approved class; backend selection stays real."""
    entries: dict[str, str] = {}

    def get(self: object, service: str, account: str) -> str | None:
        assert service == f"{SERVICE}.{account}"
        return entries.get(account)

    def save(self: object, service: str, account: str, value: str) -> None:
        assert service == f"{SERVICE}.{account}"
        entries[account] = value

    def delete(self: object, service: str, account: str) -> None:
        entries.pop(account, None)

    monkeypatch.setattr(macOS.Keyring, "get_password", get)
    monkeypatch.setattr(macOS.Keyring, "set_password", save)
    monkeypatch.setattr(macOS.Keyring, "delete_password", delete)
    return KeyringCredentialStore(macOS.Keyring()), entries  # type: ignore[no-untyped-call]


def record() -> SessionRecord:
    settings = cli_settings(callback_port=8400)
    return SessionRecord.from_grant(grant(settings.issuer), binding_key=settings.binding_key(persistent=True))


def test_whole_record_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    store, entries = backend(monkeypatch)
    value = record()
    store.save(value.binding_key, value)
    assert store.load(value.binding_key) == value
    assert len(entries) == 1
    assert "refresh-canary" not in repr(value)
    assert "refresh-canary" not in value.model_dump_json()
    assert store.delete(value.binding_key)
    assert not entries
    assert not store.delete(value.binding_key)


def test_unsupported_backend() -> None:
    with pytest.raises(StorageError, match="Unsupported"):
        KeyringCredentialStore(FailKeyring())  # type: ignore[no-untyped-call]


@pytest.mark.parametrize("method", ["get_password", "set_password", "delete_password"])
def test_locked_backend_redacts(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    store, _ = backend(monkeypatch)
    value = record()
    store.save(value.binding_key, value)

    def fail(*args: object) -> None:
        raise KeyringLocked("SECRET-CANARY raw provider body")

    monkeypatch.setattr(macOS.Keyring, method, fail)
    operation = {
        "get_password": store.load,
        "set_password": lambda key: store.save(key, value),
        "delete_password": store.delete,
    }[method]
    with pytest.raises(StorageError) as caught:
        operation(value.binding_key)
    assert "SECRET-CANARY" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("raw", ["not json secret", "x" * (MAX_RECORD_BYTES + 1), "{}", '{"schema_version":99}'])
def test_corrupt_oversize_schema(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    store, entries = backend(monkeypatch)
    key = record().binding_key
    entries[key] = raw
    with pytest.raises(StorageError):
        store.load(key)
    assert store.delete(key)


@pytest.mark.parametrize(
    "field,value",
    [
        ("generation", -1),
        ("generation", True),
        ("access_token_expires_at", "not-a-date"),
        ("extra", "secret"),
        ("binding_key", "0" * 64),
        ("access_token", ""),
        ("scopes", ["admin"]),
        ("schema_version", 2),
    ],
)
def test_invalid_record(monkeypatch: pytest.MonkeyPatch, field: str, value: object) -> None:
    store, entries = backend(monkeypatch)
    current = record()
    store.save(current.binding_key, current)
    payload = json.loads(entries[current.binding_key])
    payload[field] = value
    entries[current.binding_key] = json.dumps(payload)
    with pytest.raises(StorageError):
        store.load(current.binding_key)


def test_silent_write_or_delete_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    store, entries = backend(monkeypatch)
    current = record()
    store.save(current.binding_key, current)
    monkeypatch.setattr(macOS.Keyring, "delete_password", lambda *args: None)
    with pytest.raises(StorageError, match="deletion"):
        store.delete(current.binding_key)
    entries.clear()
    monkeypatch.setattr(macOS.Keyring, "set_password", lambda *args: None)
    with pytest.raises(StorageError, match="write"):
        store.save(current.binding_key, current)


def test_private_state_rejects_symlinks_permissions_and_corruption(tmp_path: Path) -> None:
    key = record().binding_key
    state = FileState(key, tmp_path / "state")
    state.write(SessionState(generation=8))
    state.path.chmod(0o644)
    with pytest.raises(StorageError):
        state.read()
    state.path.chmod(0o600)
    state.path.write_text('{"generation": "secret-corruption"}')
    with pytest.raises(StorageError):
        state.read()
    link = tmp_path / "link"
    link.symlink_to(state.root, target_is_directory=True)
    with pytest.raises(StorageError, match="Symlink"):
        FileState(key, link)
    state.path.unlink()
    state.path.symlink_to(tmp_path / "victim")
    with pytest.raises(StorageError):
        state.write(SessionState())


def test_probe_is_nonsecret_and_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    entries: dict[str, str] = {}
    monkeypatch.setattr(
        macOS.Keyring, "set_password", lambda self, service, account, value: entries.update({account: value})
    )
    monkeypatch.setattr(macOS.Keyring, "get_password", lambda self, service, account: entries.get(account))
    monkeypatch.setattr(macOS.Keyring, "delete_password", lambda self, service, account: entries.pop(account, None))
    store = KeyringCredentialStore(macOS.Keyring())  # type: ignore[no-untyped-call]
    store.probe()
    assert entries == {}


def test_windows_writer_replaces_one_item_without_shadow_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from types import SimpleNamespace

    from compose_api.cli.auth.windows_state import write_credential

    writes: list[dict[str, object]] = []
    monkeypatch.setitem(
        sys.modules,
        "win32cred",
        SimpleNamespace(
            CRED_TYPE_GENERIC=1,
            CRED_PERSIST_LOCAL_MACHINE=2,
            CredWrite=lambda value, flags: writes.append(value),
        ),
    )
    write_credential("service.binding", "binding", "synthetic")
    assert writes == [
        {
            "Type": 1,
            "TargetName": "service.binding",
            "UserName": "binding",
            "CredentialBlob": "synthetic",
            "Persist": 2,
            "Comment": "Compose API CLI session",
        }
    ]


def test_system_managed_ancestor_symlink_is_accepted(tmp_path: Path) -> None:
    import os
    import tempfile

    # macOS's root-owned /tmp -> /private/tmp is trusted infrastructure, not a user-controlled state symlink.
    system_tmp = Path("/tmp")  # noqa: S108 -- testing this OS-managed symlink; children use mkdtemp
    if os.name == "posix" and system_tmp.is_symlink() and system_tmp.lstat().st_uid == 0:
        with tempfile.TemporaryDirectory(dir=system_tmp) as directory:
            state = FileState(record().binding_key, Path(directory) / "state")
            state.write(SessionState(generation=1))
            assert state.read().generation == 1
    # User-controlled ancestors are always refused, on every platform.
    link = tmp_path / "user-link"
    real = tmp_path / "real"
    real.mkdir()
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(StorageError):
        FileState(record().binding_key, link / "state")
