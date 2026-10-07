"""Where sessions are kept. Each record is stored whole, under the binding key of the profile it belongs to.

There is no persistent store yet: sessions will go to the OS credential store (Keychain, Credential Manager, Secret
Service), never to a file. Until then `open_persistent_store` refuses, and a persistent sign-in stops before it opens
a browser or touches the network. The memory store serves one-command (`--ephemeral-auth`) sessions and tests.
"""

from typing import Protocol

from compose_api.cli.auth.models import SessionRecord
from compose_api.cli.config import CliSettings
from compose_api.cli.errors import StorageError


class CredentialStore(Protocol):
    def load(self, binding_key: str) -> SessionRecord | None: ...

    def save(self, binding_key: str, record: SessionRecord) -> None: ...

    def delete(self, binding_key: str) -> bool: ...


class MemoryCredentialStore:
    """Sessions held by this process only; gone when it exits or `clear` is called. Never written anywhere."""

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    def load(self, binding_key: str) -> SessionRecord | None:
        return self._records.get(binding_key)

    def save(self, binding_key: str, record: SessionRecord) -> None:
        if record.binding_key != binding_key:
            raise ValueError("a session can only be stored under its own binding key")
        self._records[binding_key] = record

    def delete(self, binding_key: str) -> bool:
        return self._records.pop(binding_key, None) is not None

    def clear(self) -> None:
        self._records.clear()


def open_persistent_store(settings: CliSettings) -> CredentialStore:
    raise StorageError(
        f"this build cannot keep a session for profile {settings.profile!r} yet: sessions are kept only in the OS"
        " credential store (Keychain, Credential Manager or Secret Service), which is not supported yet, and never"
        " in a file. Nothing was opened or sent"
    )
