"""Whole-record OS credential persistence. Secret serialization exists only at this boundary."""

import json
import re
import uuid
from typing import Protocol

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError
from pydantic import ValidationError

from compose_api.cli.auth.models import SessionRecord
from compose_api.cli.auth.state import MemoryState
from compose_api.cli.config import CliSettings
from compose_api.cli.errors import StorageError

SERVICE = "compose-api.cli.v1"
MAX_RECORD_BYTES = 65536
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

    def probe(self) -> None:
        """Detect write-locked stores before interactive sign-in using an ephemeral, non-secret marker."""
        account = uuid.uuid4().hex
        service = f"{SERVICE}.probe.{account}"
        try:
            try:
                self.backend.set_password(service, account, "compose-api-storage-probe")
                usable = self.backend.get_password(service, account) == "compose-api-storage-probe"
            finally:
                # Even a failed write may have taken effect; never leave a probe intentionally.
                if self.backend.get_password(service, account) is not None:
                    self.backend.delete_password(service, account)
                removed = self.backend.get_password(service, account) is None
        except Exception:
            raise StorageError(
                "OS credential store is locked or not writable; unlock it before signing in" + EPHEMERAL_HINT
            ) from None
        if not usable or not removed:
            raise StorageError("OS credential store could not confirm persistence; sign-in was not started")

    def _read(self, binding_key: str) -> str | None:
        try:
            return self.backend.get_password(f"{SERVICE}.{binding_key}", binding_key)
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
        raw = json.dumps(payload, separators=(",", ":"))
        # Windows generic credentials have a 2560-byte blob limit; never split a record.
        windows = type(self.backend).__module__ == "keyring.backends.Windows"
        if len(raw.encode()) > MAX_RECORD_BYTES or (windows and len(raw.encode("utf-16-le")) > 2560):
            raise StorageError("Credential record exceeds this OS backend's atomic item limit; session not saved")
        try:
            if windows:
                from compose_api.cli.auth.windows_state import write_credential

                # keyring's Windows set_password backs up the previous item under a compound name. Use the
                # native single-item replacement instead so spent credentials never survive as shadow copies.
                write_credential(f"{SERVICE}.{binding_key}", binding_key, raw)
            else:
                self.backend.set_password(f"{SERVICE}.{binding_key}", binding_key, raw)
            saved = self.backend.get_password(f"{SERVICE}.{binding_key}", binding_key)
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
