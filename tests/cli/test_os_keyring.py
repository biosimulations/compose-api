"""Real OS credential stores: macOS Keychain, Linux Secret Service, Windows Credential Manager.

Opt-in, because these write to the machine's actual store: set COMPOSE_API_TEST_OS_KEYRING=1. The record is synthetic,
stored under a random binding key that can never collide with a real session, and deleted in a `finally` even when an
assertion fails. The tests reach the real backend through `keyring.core`, past the suite's refusing default.

This module and its records (tests/fixtures/session_records.py) import nothing from the server, so it also runs alone in
a minimal environment: `python -m pytest --noconftest -o addopts= tests/cli/test_os_keyring.py`.
"""

import os
import secrets

import keyring.core
import pytest
from compose_api_client.auth.storage import SERVICE, KeyringCredentialStore
from pydantic import SecretStr

from tests.fixtures.session_records import (
    HEAVY_PERMISSIONS,
    HEAVY_ROLES,
    realistic_session,
    serialized,
    with_parity,
    with_size,
)

WINDOWS_CREDENTIAL_BLOB_LIMIT = 2560  # bytes in one generic credential (CRED_MAX_CREDENTIAL_BLOB_SIZE)

opt_in = pytest.mark.skipif(
    os.environ.get("COMPOSE_API_TEST_OS_KEYRING") != "1",
    reason="writes to this machine's real credential store; set COMPOSE_API_TEST_OS_KEYRING=1 to run",
)


def test_a_realistic_session_fits_a_windows_credential_only_as_utf8() -> None:
    """Measured, not assumed: why the CLI writes Credential Manager items itself (#320). keyring writes UTF-16."""
    raw = serialized(realistic_session("0" * 64))
    assert len(raw.encode()) < WINDOWS_CREDENTIAL_BLOB_LIMIT
    assert len(raw.encode("utf-16-le")) > WINDOWS_CREDENTIAL_BLOB_LIMIT


def test_a_session_with_a_heavier_access_token_still_fits_a_windows_credential() -> None:
    """Headroom, measured. Today's token carries one role and no permissions, leaving about 850 bytes of the item, and
    a record that outgrows it is refused only after a completed sign-in. Six roles and sixteen RBAC permissions (each
    about 25 bytes of the token) still fit, with about 300 bytes to spare."""
    light = serialized(realistic_session("0" * 64))
    heavy = serialized(realistic_session("0" * 64, roles=HEAVY_ROLES, permissions=HEAVY_PERMISSIONS))
    assert len(heavy) - len(light) > 500, "the heavier claims are in the token"
    assert len(heavy.encode()) <= WINDOWS_CREDENTIAL_BLOB_LIMIT


@opt_in
@pytest.mark.parametrize("parity", [0, 1], ids=["even", "odd"])
def test_the_platform_store_keeps_a_realistic_session_whole(parity: int) -> None:
    """Both lengths, for Windows, where two bytes of the record make one UTF-16 unit: an odd length is evened out,
    and an even one is what keyring's own reader would misread as UTF-16."""
    backend = keyring.core.get_keyring()
    store = KeyringCredentialStore(backend)  # refuses anything but the three approved OS stores
    store.probe()
    binding = secrets.token_hex(32)
    record = with_parity(realistic_session(binding), parity)
    raw = serialized(record)
    assert len(raw) % 2 == parity
    try:
        store.save(binding, record)
        assert store.load(binding) == record
        if type(backend).__module__ == "keyring.backends.Windows":
            import win32cred

            item = win32cred.CredRead(Type=win32cred.CRED_TYPE_GENERIC, TargetName=f"{SERVICE}.{binding}")
            assert item["CredentialBlob"] == raw.encode() + b"\0" * parity, "one item holds the record as UTF-8"
        else:
            assert backend.get_password(f"{SERVICE}.{binding}", binding) == raw, "one item holds the whole record"
        assert binding in f"{SERVICE}.{binding}" and "@" not in f"{SERVICE}.{binding}", "no email in the item name"
    finally:
        store.delete(binding)
    assert store.load(binding) is None
    assert backend.get_password(f"{SERVICE}.{binding}", binding) is None


@opt_in
def test_the_platform_store_replaces_a_session_in_place() -> None:
    """A renewal overwrites the item; no second copy of a spent credential is left behind."""
    backend = keyring.core.get_keyring()
    store = KeyringCredentialStore(backend)
    binding = secrets.token_hex(32)
    small = realistic_session(binding).model_copy(
        update={"access_token": SecretStr("a" * 200), "refresh_token": SecretStr("first")}
    )
    successor = small.model_copy(update={"refresh_token": SecretStr("second"), "generation": 1})
    try:
        store.save(binding, small)
        store.save(binding, successor)
        loaded = store.load(binding)
        assert loaded is not None and loaded.refresh_token == SecretStr("second") and loaded.generation == 1
        if type(backend).__module__ == "keyring.backends.Windows":
            import pywintypes
            import win32cred

            # keyring's own set_password would have moved the first item to `<account>@<service>`.
            with pytest.raises(pywintypes.error) as missing:
                win32cred.CredRead(Type=win32cred.CRED_TYPE_GENERIC, TargetName=f"{binding}@{SERVICE}.{binding}")
            assert missing.value.winerror == 1168, "no shadow copy of the spent credential"
            item = win32cred.CredRead(Type=win32cred.CRED_TYPE_GENERIC, TargetName=f"{SERVICE}.{binding}")
            raw = serialized(successor)
            assert item["CredentialBlob"] == raw.encode() + b"\0" * (len(raw) % 2), "the one item holds the successor"
    finally:
        store.delete(binding)
    assert store.load(binding) is None


@opt_in
@pytest.mark.parametrize("size", [WINDOWS_CREDENTIAL_BLOB_LIMIT - 1, WINDOWS_CREDENTIAL_BLOB_LIMIT])
def test_the_platform_store_keeps_a_session_at_the_windows_item_limit(size: int) -> None:
    """A record of 2559 bytes is the tightest case on Windows: its pad byte makes the blob exactly 2560."""
    backend = keyring.core.get_keyring()
    store = KeyringCredentialStore(backend)
    binding = secrets.token_hex(32)
    record = with_size(realistic_session(binding), size)
    assert len(serialized(record)) == size
    try:
        store.save(binding, record)
        assert store.load(binding) == record
        if type(backend).__module__ == "keyring.backends.Windows":
            import win32cred

            item = win32cred.CredRead(Type=win32cred.CRED_TYPE_GENERIC, TargetName=f"{SERVICE}.{binding}")
            assert len(item["CredentialBlob"]) == WINDOWS_CREDENTIAL_BLOB_LIMIT
    finally:
        store.delete(binding)
    assert store.load(binding) is None
