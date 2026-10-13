"""Non-secret generation/journal state and process locks. Never receives credential material."""

import asyncio
import json
import os
import re
import stat
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import portalocker
from platformdirs import user_state_path
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from compose_api.cli.errors import StorageError


class SessionState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    version: Literal[1] = 1
    generation: int = Field(default=0, ge=0)
    active: bool = False
    journal: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class FileState:
    """Private local state with owner-only POSIX permissions or a protected Windows ACL.

    Metadata is fsynced before atomic replacement and the directory is fsynced afterwards. Lock files are never
    replaced/deleted, including at logout, so another process cannot lock a different inode for the same binding.
    """

    def __init__(self, binding: str, root: Path | None = None) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", binding):
            raise StorageError("Invalid session binding")
        if os.name not in {"posix", "nt"}:
            raise StorageError("Unsupported platform for private session state")
        self.root = root if root is not None else user_state_path("compose-api") / "sessions"
        self.binding = binding
        self.path = self.root / f"{binding}.json"
        self._prepare()

    def _prepare(self) -> None:
        try:
            # Check ancestors before mkdir, including paths that resolve into an attacker-controlled directory.
            for path in reversed((self.root, *self.root.parents)):
                if (path.is_symlink() or path.is_junction()) and not self._trusted_system_link(path):
                    raise StorageError("Symlinked session state paths are refused")
            existed = self.root.exists()
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name == "nt":
                from compose_api.cli.auth import windows_state

                if not existed:
                    windows_state.protect(self.root)
                windows_state.validate(self.root)
            else:
                info = self.root.stat()
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise StorageError("Session directory must be owned by the current user with permissions 0700")
        except OSError:
            raise StorageError("Cannot prepare private session state directory") from None

    def _trusted_system_link(self, path: Path) -> bool:
        # macOS /var and /tmp are root-managed symlinks. Trust only administrator-controlled ancestors,
        # never a user-controlled symlink or the session directory itself.
        if os.name != "posix" or path == self.root:
            return False
        parent = path.parent.stat()
        return (
            path.lstat().st_uid == 0
            and parent.st_uid == 0
            and not parent.st_mode & 0o022
            and path.resolve(strict=True).stat().st_uid == 0
        )

    def _open(self, path: Path, *, create: bool = False) -> int:
        if path.is_symlink() or path.is_junction():
            raise StorageError("Symlinked session state files are refused")
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        if create:
            flags |= os.O_CREAT
        descriptor = os.open(path, flags, 0o600)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or (os.name == "posix" and info.st_uid != os.getuid())
            or (os.name == "posix" and stat.S_IMODE(info.st_mode) != 0o600)
            or info.st_nlink != 1
        ):
            os.close(descriptor)
            raise StorageError("Session files must be private, owned, regular files")
        if os.name == "nt":
            from compose_api.cli.auth import windows_state

            try:
                windows_state.validate(path)
            except BaseException:
                os.close(descriptor)
                raise
        return descriptor

    @asynccontextmanager
    async def lock(self, *, login: bool = False, timeout: float = 30) -> AsyncIterator[None]:
        self._prepare()
        path = self.root / f"{self.binding}.{'login' if login else 'session'}.lock"
        try:
            descriptor = self._open(path, create=True)
        except OSError:
            raise StorageError("Cannot open private session lock") from None
        with os.fdopen(descriptor, "r+") as handle:
            deadline = time.monotonic() + (0 if login else timeout)
            while True:
                try:
                    portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
                    break
                except portalocker.exceptions.LockException:
                    if time.monotonic() >= deadline:
                        raise StorageError("Session is busy; finish the other sign-in or retry later") from None
                    # Nonblocking OS lock polling keeps cancellation and other async operations responsive.
                    await asyncio.sleep(0.05)
            try:
                yield
            finally:
                portalocker.unlock(handle)

    def read(self) -> SessionState:
        try:
            descriptor = self._open(self.path)
        except FileNotFoundError:
            return SessionState()
        except OSError:
            raise StorageError("Cannot read session state") from None
        try:
            with os.fdopen(descriptor) as handle:
                raw = handle.read(4097)
            if len(raw) > 4096:
                raise StorageError("Oversized session metadata; local state repair required")
            return SessionState.model_validate_json(raw)
        except (ValueError, ValidationError):
            raise StorageError("Corrupt session metadata; repair private state before using credentials") from None

    def write(self, state: SessionState) -> None:
        self._prepare()
        temporary: str | None = None
        try:
            # Existing unsafe metadata must not be overwritten silently.
            if self.path.exists() or self.path.is_symlink():
                os.close(self._open(self.path))
            descriptor, temporary = tempfile.mkstemp(dir=self.root, prefix=".state-")
            with os.fdopen(descriptor, "w") as handle:
                json.dump(state.model_dump(), handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            if os.name == "nt":
                from compose_api.cli.auth import windows_state

                windows_state.validate(Path(temporary))
                windows_state.replace(temporary, self.path)
                temporary = None
            else:
                os.replace(temporary, self.path)
                temporary = None
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except OSError:
            raise StorageError("Cannot durably save session metadata; reauthentication may be required") from None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


class MemoryState(FileState):
    """Explicit injected/ephemeral state; no filesystem or platform keychain access."""

    def __init__(self, initial: SessionState | None = None) -> None:
        self.value = initial or SessionState()
        self.session_lock = asyncio.Lock()
        self.login_lock = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, *, login: bool = False, timeout: float = 30) -> AsyncIterator[None]:
        selected = self.login_lock if login else self.session_lock
        if login and selected.locked():
            raise StorageError("A sign-in is already running for this profile")
        try:
            async with asyncio.timeout(timeout):
                await selected.acquire()
        except TimeoutError:
            raise StorageError("Session is busy; retry later") from None
        try:
            yield
        finally:
            selected.release()

    def read(self) -> SessionState:
        return self.value

    def write(self, state: SessionState) -> None:
        self.value = state
