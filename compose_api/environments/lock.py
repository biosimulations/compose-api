"""A shared environment version's lock (docs/plan-environment-versions.md, V2, step 3).

The spec (the registry's library list and the pbest release the runtime comes from) is resolved once, by uv, for the
image's Python and platform, with nothing newer than ``resolved_at``. The result pins every PyPI package, transitive
ones included; its sha256 is the version's identity, and the definition installs exactly it
(``compose_api/environments/definition.py``). Conda packages (readdy) are installed from conda-forge by version and
are not in the lock.

    uv run python -m compose_api.environments.lock [--resolved-at 2026-10-25T18:00:00Z] [--definition]
"""

import argparse
import asyncio
import datetime
import hashlib
import importlib.metadata
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from compose_api.simulation.simulator_registry import registry_libraries

#: the image's Python (definition.py's micromamba environment) and the platform its wheels must run on
PYTHON_VERSION = "3.12"
PYTHON_PLATFORM = "x86_64-manylinux_2_28"
PBEST_REPOSITORY = "https://github.com/biosimulations/pbest"
LOCK_TIMEOUT_SECONDS = 600.0
_SPEC_FILE = "spec.in"  # the name the lock's "# via -r" annotations carry


class LockError(RuntimeError):
    """uv could not resolve the spec; the message carries its explanation."""


@dataclass(frozen=True)
class SharedSpec:
    """What a shared version is made from: library entries as in ``simulator_registry.json``, and the pbest release
    (a git tag) whose runtime the image runs. ``pbest`` None leaves the runtime out (tests)."""

    libraries: list[dict[str, str]] = field(default_factory=list)
    pbest: str | None = None

    @classmethod
    def from_registry(cls) -> "SharedSpec":
        """The repository's library list, with the pbest release this service runs against."""
        return cls(libraries=registry_libraries(), pbest=importlib.metadata.version("pbest"))

    def as_json(self) -> dict[str, Any]:
        return {"libraries": self.libraries, "pbest": self.pbest}

    def pypi(self) -> list[str]:
        """The requirements uv resolves, one per line of its input."""
        pins = [f"{lib['name']}=={lib['version']}" if lib.get("version") else lib["name"] for lib in self._of("pypi")]
        if self.pbest is not None:
            pins.append(f"pbest @ git+{PBEST_REPOSITORY}@{self.pbest}")
        return pins

    def conda(self) -> list[str]:
        """``name=version`` for each conda-forge library."""
        return [f"{lib['name']}={lib['version']}" if lib.get("version") else lib["name"] for lib in self._of("conda")]

    def _of(self, registry: str) -> list[dict[str, str]]:
        return [lib for lib in self.libraries if (lib["package_registry"] == "pypi") == (registry == "pypi")]


@dataclass(frozen=True)
class Lock:
    text: str
    resolved_at: datetime.datetime  # UTC, naive (as the database stores it)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def exclude_newer(resolved_at: datetime.datetime) -> str:
    """``resolved_at`` (naive means UTC) in the form uv takes."""
    utc = (
        resolved_at.replace(tzinfo=datetime.UTC) if resolved_at.tzinfo is None else resolved_at.astimezone(datetime.UTC)
    )
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


async def compile_lock(spec: SharedSpec, resolved_at: datetime.datetime, uv: str | None = None) -> Lock:
    """Resolve ``spec`` with nothing newer than ``resolved_at``. The same inputs give the same lock."""
    executable = uv or shutil.which("uv")
    if executable is None:
        raise LockError("uv is not installed")
    stamp = exclude_newer(resolved_at)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / _SPEC_FILE).write_text("\n".join(spec.pypi()) + "\n")
        process = await asyncio.create_subprocess_exec(
            executable, "pip", "compile", _SPEC_FILE,
            "--python-version", PYTHON_VERSION, "--python-platform", PYTHON_PLATFORM,
            "--exclude-newer", stamp, "--no-header", "--quiet",
            cwd=tmp, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        try:
            out, err = await asyncio.wait_for(process.communicate(), LOCK_TIMEOUT_SECONDS)
        except TimeoutError:
            process.kill()
            raise LockError(f"uv pip compile took longer than {LOCK_TIMEOUT_SECONDS:.0f} s") from None
    if process.returncode != 0:
        raise LockError(err.decode(errors="replace").strip() or f"uv pip compile exited {process.returncode}")
    naive = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    return Lock(text=out.decode(), resolved_at=naive)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Print the lock (or definition) of the repository's shared spec.")
    parser.add_argument("--resolved-at", type=datetime.datetime.fromisoformat, default=None, help="default: now")
    parser.add_argument("--definition", action="store_true", help="print the Apptainer definition instead")
    args = parser.parse_args(argv)
    spec = SharedSpec.from_registry()
    lock = asyncio.run(compile_lock(spec, args.resolved_at or datetime.datetime.now(datetime.UTC)))
    if args.definition:
        from compose_api.environments.definition import shared_definition

        sys.stdout.write(shared_definition(spec, lock).representation)
    else:
        sys.stdout.write(lock.text)
    sys.stderr.write(f"resolved at {exclude_newer(lock.resolved_at)}, sha256 {lock.sha256}\n")


if __name__ == "__main__":
    main()
