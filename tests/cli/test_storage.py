"""OS backend contract without touching the developer's keychain."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from compose_api_client.auth import state as state_module
from compose_api_client.auth.models import SessionRecord
from compose_api_client.auth.state import FileState, SessionState, _is_junction
from compose_api_client.auth.storage import (
    MAX_RECORD_BYTES,
    PROBE_VALUE,
    SERVICE,
    WINDOWS_ITEM_BYTES,
    KeyringCredentialStore,
)
from compose_api_client.auth.windows_state import read_credential, write_credential
from compose_api_client.ext.errors import StorageError
from keyring.backends import macOS
from keyring.backends.fail import Keyring as FailKeyring
from keyring.errors import KeyringLocked

from tests.cli.test_os_keyring import realistic_session, serialized, with_parity, with_size
from tests.cli.test_session import grant
from tests.fixtures.cli_fixtures import FakeCredentialManager, WinError, cli_settings


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


@pytest.mark.parametrize(
    "raw",
    ["not json secret", pytest.param("x" * (MAX_RECORD_BYTES + 1), id="oversized"), "{}", '{"schema_version":99}'],
)
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
    import os

    state.write(SessionState(generation=8))
    state.path.write_text('{"generation": "secret-corruption"}')
    with pytest.raises(StorageError):
        state.read()
    state.write(SessionState(generation=8))
    if os.name == "posix":
        state.path.chmod(0o644)
    else:
        import win32security

        everyone = win32security.ConvertStringSidToSid("S-1-1-0")
        acl = win32security.ACL()
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, 0, 0x001F01FF, everyone)
        win32security.SetNamedSecurityInfo(
            str(state.path),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            acl,
            None,
        )
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


@pytest.mark.parametrize("value", ['{"a":1}', '{"ab":1}'], ids=["odd", "even"])
def test_windows_item_holds_the_value_as_utf8(windows_credential_manager: FakeCredentialManager, value: str) -> None:
    """Not as UTF-16, which would double a session past the item's limit (#320). An odd length gains a NUL; an even
    one is what keyring's own reader would misread, as it decodes a blob as UTF-16 first."""
    write_credential("service.binding", "binding", value)
    assert windows_credential_manager.items["service.binding"]["CredentialBlob"] == value.encode() + b"\0" * (
        len(value) % 2
    )
    assert read_credential("service.binding", "binding") == value


def test_windows_writer_replaces_one_item_without_shadow_copy(
    windows_credential_manager: FakeCredentialManager,
) -> None:
    write_credential("service.binding", "binding", "first")
    write_credential("service.binding", "binding", "second")
    assert list(windows_credential_manager.items) == ["service.binding"]
    assert {**windows_credential_manager.items["service.binding"], "CredentialBlob": None} == {
        "Type": 1,
        "TargetName": "service.binding",
        "UserName": "binding",
        "CredentialBlob": None,
        "Persist": 2,
        "Comment": "Compose API CLI session",
    }
    assert read_credential("service.binding", "binding") == "second"


def test_windows_reader_finds_only_this_accounts_item(windows_credential_manager: FakeCredentialManager) -> None:
    assert read_credential("service.binding", "binding") is None
    write_credential("service.binding", "someone-else", "value")
    assert read_credential("service.binding", "binding") is None


@pytest.mark.parametrize("value", ["caf\u00e9", "nul\0"], ids=["non-ascii", "nul"])
def test_windows_writer_refuses_what_it_cannot_store_exactly(
    windows_credential_manager: FakeCredentialManager, value: str
) -> None:
    with pytest.raises(ValueError, match=r"ascii|NUL"):
        write_credential("service.binding", "binding", value)
    assert windows_credential_manager.writes == []


def windows_store() -> KeyringCredentialStore:
    from keyring.backends.Windows import WinVaultKeyring

    return KeyringCredentialStore(WinVaultKeyring())  # type: ignore[no-untyped-call]


@pytest.mark.parametrize("parity", [0, 1], ids=["even", "odd"])
def test_windows_store_keeps_a_realistic_session_in_one_item(
    windows_credential_manager: FakeCredentialManager, parity: int
) -> None:
    store = windows_store()
    binding = record().binding_key
    session = with_parity(realistic_session(binding), parity)
    raw = serialized(session)
    assert len(raw) % 2 == parity
    store.save(binding, session)
    assert store.load(binding) == session
    assert list(windows_credential_manager.items) == [f"{SERVICE}.{binding}"]
    assert windows_credential_manager.items[f"{SERVICE}.{binding}"]["CredentialBlob"] == raw.encode() + b"\0" * parity
    assert store.delete(binding)  # through keyring's own Windows backend
    assert windows_credential_manager.items == {}
    assert store.load(binding) is None


@pytest.mark.parametrize("size", [WINDOWS_ITEM_BYTES - 1, WINDOWS_ITEM_BYTES])
def test_windows_store_takes_a_record_up_to_the_item_limit(
    windows_credential_manager: FakeCredentialManager, size: int
) -> None:
    """2559 bytes is the tightest case: its pad byte brings the blob to exactly the item's 2560."""
    store = windows_store()
    binding = record().binding_key
    session = with_size(realistic_session(binding), size)
    assert len(serialized(session)) == size
    store.save(binding, session)
    assert store.load(binding) == session
    assert len(windows_credential_manager.items[f"{SERVICE}.{binding}"]["CredentialBlob"]) == WINDOWS_ITEM_BYTES


def test_windows_store_refuses_a_record_too_big_for_one_item_before_writing(
    windows_credential_manager: FakeCredentialManager,
) -> None:
    store = windows_store()
    binding = record().binding_key
    oversized = with_size(realistic_session(binding), WINDOWS_ITEM_BYTES + 1)
    # The refusal comes after a completed sign-in, so it says what still works.
    with pytest.raises(StorageError, match=r"atomic item limit.*--ephemeral-auth"):
        store.save(binding, oversized)
    assert windows_credential_manager.writes == []
    assert store.load(binding) is None


def test_windows_probe_writes_as_a_session_is_saved(
    windows_credential_manager: FakeCredentialManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Natively, as UTF-8 with CRED_PERSIST_LOCAL_MACHINE, not as keyring writes (UTF-16, CRED_PERSIST_ENTERPRISE).
    The probe value's odd length takes the padded path."""
    written: list[dict[str, Any]] = []
    write = windows_credential_manager.CredWrite

    def recording(credential: dict[str, Any], flags: int) -> None:
        write(credential, flags)
        written.append(windows_credential_manager.items[credential["TargetName"]])

    monkeypatch.setattr(windows_credential_manager, "CredWrite", recording)
    windows_store().probe()
    [probe] = written
    assert probe["Persist"] == FakeCredentialManager.CRED_PERSIST_LOCAL_MACHINE
    assert probe["CredentialBlob"] == PROBE_VALUE.encode() + b"\0" and len(PROBE_VALUE) % 2 == 1
    assert windows_credential_manager.items == {}, "deleted through keyring, as logout deletes"


def test_a_windows_store_refusing_native_writes_fails_the_probe(
    windows_credential_manager: FakeCredentialManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caught before the browser opens, even while keyring's own write path still works."""
    write = windows_credential_manager.CredWrite

    def refuse_native(credential: dict[str, Any], flags: int) -> None:
        if credential["Persist"] == FakeCredentialManager.CRED_PERSIST_LOCAL_MACHINE:
            raise WinError(5, "CredWrite", "Access is denied.")
        write(credential, flags)

    monkeypatch.setattr(windows_credential_manager, "CredWrite", refuse_native)
    with pytest.raises(StorageError, match="locked or not writable"):
        windows_store().probe()
    assert windows_credential_manager.items == {}


def test_windows_store_refuses_an_item_that_is_not_utf8(windows_credential_manager: FakeCredentialManager) -> None:
    binding = record().binding_key
    windows_credential_manager.items[f"{SERVICE}.{binding}"] = {"UserName": binding, "CredentialBlob": b"\xff{}"}
    with pytest.raises(StorageError, match="Invalid credential encoding"):
        windows_store().load(binding)


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


class _Lstat:
    """Stands in for a `Path` whose `lstat()` gives this result (or raises it)."""

    def __init__(self, result: object) -> None:
        self.result = result

    def lstat(self) -> object:
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (SimpleNamespace(st_reparse_tag=0xA0000003), True),  # IO_REPARSE_TAG_MOUNT_POINT: a directory junction
        (SimpleNamespace(st_reparse_tag=0xA000000C), False),  # IO_REPARSE_TAG_SYMLINK: is_symlink() covers it
        (SimpleNamespace(st_reparse_tag=0), False),  # an ordinary Windows file or directory
        (SimpleNamespace(), False),  # a POSIX stat result has no reparse tag
        (FileNotFoundError(), False),
    ],
)
def test_junctions_are_detected_without_path_is_junction(result: object, expected: bool) -> None:
    # `Path.is_junction()` is 3.12+ and the client supports 3.11, so the reparse tag is read directly.
    assert _is_junction(cast(Path, _Lstat(result))) is expected


def test_real_paths_are_not_junctions(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("")
    assert not _is_junction(tmp_path)
    assert not _is_junction(tmp_path / "file")
    assert not _is_junction(tmp_path / "missing")


@pytest.mark.parametrize("where", ["ancestor", "file"])
def test_a_junction_anywhere_in_the_state_path_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    key = record().binding_key
    state = FileState(key, tmp_path / "state")
    state.write(SessionState(generation=1))
    junction = tmp_path if where == "ancestor" else state.path
    monkeypatch.setattr(state_module, "_is_junction", lambda path: path == junction)
    with pytest.raises(StorageError, match="Symlinked session state"):
        if where == "ancestor":
            FileState(key, tmp_path / "state")
        else:
            state.read()


@pytest.mark.skipif(os.name != "nt", reason="directory junctions exist only on Windows")
def test_a_real_windows_junction_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    junction = tmp_path / "junction"
    subprocess.run(  # noqa: S603 -- fixed arguments; mklink is a cmd built-in, so there is no executable to resolve
        ["cmd", "/c", "mklink", "/J", str(junction), str(real)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    assert _is_junction(junction) and not junction.is_symlink() and not _is_junction(real)
    with pytest.raises(StorageError, match="Symlinked session state paths"):
        FileState(record().binding_key, junction / "state")
