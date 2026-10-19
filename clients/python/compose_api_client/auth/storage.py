"""Whole-record OS credential persistence. Secret serialization exists only at this boundary."""

from __future__ import annotations

import json
import re
import uuid
from typing import Protocol

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError
from pydantic import ValidationError

from compose_api_client.auth.models import SessionRecord
from compose_api_client.auth.state import MemoryState
from compose_api_client.ext.errors import StorageError
from compose_api_client.profiles import CliSettings

SERVICE = "compose-api.cli.v1"
MAX_RECORD_BYTES = 65536
WINDOWS_ITEM_BYTES = 2560  # one Credential Manager blob (CRED_MAX_CREDENTIAL_BLOB_SIZE), holding the record as UTF-8
PROBE_VALUE = "compose-api-storage-probe"  # non-secret; an odd length, so a Windows probe takes the padded path
# Where there is no usable OS store, the memory-only alternative is the only safe one; there is no file fallback.
EPHEMERAL_HINT = " (on a host without one, API commands can sign in for a single run with --ephemeral-auth)"
APPROVED_BACKENDS = frozenset({
    ("keyring.backends.macOS", "Keyring"),
    ("keyring.backends.SecretService", "Keyring"),
    ("keyring.backends.Windows", "WinVaultKeyring"),
})


class CredentialStore(Protocol):
    def load(self, binding_key: str) -> SessionRecord | None: ...
    def save(self, binding_key: str, record: SessionRecord) -> None: ...
    def delete(self, binding_key: str) -> bool: ...


def validate_record(binding_key: str, record: SessionRecord) -> None:
    if (
        record.binding_key != binding_key
        or not re.fullmatch(r"[0-9a-f]{64}", binding_key)
        or not record.access_token.get_secret_value()
        or (record.refresh_token is not None and not record.refresh_token.get_secret_value())
        or not record.identity.subject
        or not record.identity.issuer.startswith("https://")
        or not record.identity.issuer.endswith("/")
        or "openid" not in record.scopes
        or not set(record.scopes) <= {"openid", "profile", "email", "offline_access"}
    ):
        raise StorageError("Invalid credential record or profile binding; use auth logout --local-only then sign in")


class MemoryCredentialStore:
    """Explicit process-local store for ephemeral flows and injected tests; never a fallback."""

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}
        self.states: dict[str, MemoryState] = {}

    def load(self, binding_key: str) -> SessionRecord | None:
        return self._records.get(binding_key)

    def save(self, binding_key: str, record: SessionRecord) -> None:
        validate_record(binding_key, record)
        self._records[binding_key] = record

    def delete(self, binding_key: str) -> bool:
        return self._records.pop(binding_key, None) is not None

    def clear(self) -> None:
        self._records.clear()


class KeyringCredentialStore:
    """One keychain item per binding. Unknown/chained/plaintext backends are rejected."""

    def __init__(self, backend: KeyringBackend) -> None:
        backend_type = type(backend)
        if (backend_type.__module__, backend_type.__name__) not in APPROVED_BACKENDS:
            raise StorageError(
                "Unsupported OS credential backend; configure Keychain, Credential Manager or Secret Service"
                + EPHEMERAL_HINT
            )
        self.backend = backend
        # Credential Manager items, the probe's included, are written and read natively (windows_state); keyring
        # still deletes them.
        self.windows = backend_type.__module__ == "keyring.backends.Windows"

    def _get(self, service: str, account: str) -> str | None:
        if self.windows:
            from compose_api_client.auth.windows_state import read_credential

            return read_credential(service, account)
        return self.backend.get_password(service, account)

    def _set(self, service: str, account: str, value: str) -> None:
        if self.windows:
            from compose_api_client.auth.windows_state import write_credential

            # keyring's Windows set_password backs up the previous item under a compound name, and writes UTF-16.
            # Use the native single-item replacement instead, so spent credentials never survive as shadow copies
            # and the record is stored as UTF-8.
            write_credential(service, account, value)
        else:
            self.backend.set_password(service, account, value)

    def probe(self) -> None:
        """Detect write-locked stores before interactive sign-in using an ephemeral, non-secret marker.

        It is written and read as a session is (natively on Windows), so a store that would refuse the save fails
        here, before the browser opens, and deleted through keyring, as logout deletes.
        """
        account = uuid.uuid4().hex
        service = f"{SERVICE}.probe.{account}"
        try:
            try:
                self._set(service, account, PROBE_VALUE)
                usable = self._get(service, account) == PROBE_VALUE
            finally:
                # Even a failed write may have taken effect; never leave a probe intentionally.
                if self._get(service, account) is not None:
                    self.backend.delete_password(service, account)
                removed = self._get(service, account) is None
        except Exception:
            raise StorageError(
                "OS credential store is locked or not writable; unlock it before signing in" + EPHEMERAL_HINT
            ) from None
        if not usable or not removed:
            raise StorageError("OS credential store could not confirm persistence; sign-in was not started")

    def _read(self, binding_key: str) -> str | None:
        try:
            return self._get(f"{SERVICE}.{binding_key}", binding_key)
        except Exception:
            # Third-party OS bindings have heterogeneous errors. Never propagate their text or cause.
            raise StorageError("OS credential store is unavailable or locked; unlock it and retry") from None

    def load(self, binding_key: str) -> SessionRecord | None:
        raw = self._read(binding_key)
        if raw is None:
            return None
        try:
            size = len(raw.encode())
        except (AttributeError, UnicodeError):
            raise StorageError("Invalid credential encoding; use auth logout --local-only") from None
        if size > MAX_RECORD_BYTES:
            raise StorageError("Oversized credential record; use auth logout --local-only")
        try:
            record = SessionRecord.model_validate_json(raw, strict=True)
            validate_record(binding_key, record)
            return record
        except (ValueError, ValidationError):
            raise StorageError(
                "Corrupt or oversized credential record; use auth logout --local-only then sign in"
            ) from None

    def save(self, binding_key: str, record: SessionRecord) -> None:
        validate_record(binding_key, record)
        payload = record.model_dump(mode="json")
        payload["access_token"] = record.access_token.get_secret_value()
        payload["refresh_token"] = None if record.refresh_token is None else record.refresh_token.get_secret_value()
        # ASCII, as the Windows item requires (`write_credential`): non-ASCII characters are escaped, never written.
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        # Never split a record. A realistic session (about 1700 bytes) fits a Credential Manager item only as UTF-8.
        if len(raw.encode()) > (WINDOWS_ITEM_BYTES if self.windows else MAX_RECORD_BYTES):
            raise StorageError(
                "Credential record exceeds this OS backend's atomic item limit, so the session was not saved; API"
                " commands can still sign in for a single run with --ephemeral-auth"
            )
        try:
            self._set(f"{SERVICE}.{binding_key}", binding_key, raw)
            saved = self._get(f"{SERVICE}.{binding_key}", binding_key)
        except Exception:
            raise StorageError(
                "OS credential write could not be confirmed; sign in again after repairing the store"
            ) from None

        if saved != raw:
            raise StorageError("OS credential write could not be confirmed; sign in again")

    def delete(self, binding_key: str) -> bool:
        # Do not parse: logout can erase corrupt records as well.
        existed = self._read(binding_key) is not None
        try:
            if existed:
                self.backend.delete_password(f"{SERVICE}.{binding_key}", binding_key)
        except PasswordDeleteError:
            pass  # Verify absence below: some stores report a concurrently missing item as an error.
        except Exception:
            raise StorageError("Local credential deletion failed; unlock the OS store and retry logout") from None
        if self._read(binding_key) is not None:
            raise StorageError("Local credential deletion failed; unlock the OS store and retry logout")
        return existed


def open_persistent_store(settings: CliSettings, *, check: bool = True, writable: bool = True) -> CredentialStore:
    try:
        backend = keyring.get_keyring()
    except Exception:
        raise StorageError(
            "OS credential backend is unavailable; persistent sign-in requires a supported keyring" + EPHEMERAL_HINT
        ) from None
    store = KeyringCredentialStore(backend)
    if writable:
        store.probe()
    if check:
        store.load(settings.binding_key(persistent=True))  # Detect a locked store before opening a browser.
    return store
