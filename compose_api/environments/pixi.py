"""Composed environments as pixi (docs/plan-environment-composition.md, C2, step 3).

A composed environment is a set of registry entries. Its spec (:class:`ComposedSpec`) is what they say about
installing themselves, plus the common core and the date nothing newer may be resolved than; :func:`pixi_toml` turns it
into a pixi workspace, which an unprivileged Job locks (``build_k8s.lock_job``); and :func:`composed_definition` is the
Apptainer definition that installs exactly that lock, frozen, and runs documents with compose-api's runner (runtime
contract 2). The lock is in the definition, so the definition's hash, the simulator's identity, changes exactly when
the lock does, as for a shared version (``definition.py``).
"""

import datetime
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compose_api.registry.environments import Composition, EnvironmentSpec
from compose_api.registry.manifest import Manifest, RegistryEntry
from compose_api.simulation.containerization import ContainerizationEngine, ContainerizationFileRepr

RUNTIME_CONTRACT = 2  # compose-api's runner (environments/runner.py) answers the job; a change to it is a new contract
WORKSPACE = "/opt/environment"
RUNNER = "/opt/compose-api/runner.py"
SHELL_HOOK = f"{WORKSPACE}/shell-hook.sh"
# How to enter a composed image's Python: pixi's activation (conda activation scripts, for dolfinx or PETSc) first
PYTHON = ("/bin/bash", "-c", f'source {SHELL_HOOK} && exec python "$@"', "python")
DEFAULT_PYTHON_VERSION = "3.12"
# Development tooling that workspaces send to a branch of its own repository (`[tool.uv.sources]`). pixi follows those
# sources for a package it installs from git, so the only candidate is the branch's tip, whose requirements can exceed
# the core's pins (viva-superpowers 0.24.0 needs bigraph-schema>=1.8.2, the core has 1.8.1) and make the lock
# unsatisfiable. The lock takes these from the package index instead, unless an entry installs one itself (pixi 0.68.1
# has no switch to ignore sources).
INDEX_ONLY = ("pbg-superpowers", "viva-superpowers", "vivarium-workbench")


def _toml(value: object) -> str:
    """A TOML value from strings, lists of strings and inline tables (JSON's string escapes are TOML's)."""
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(k)} = {_toml(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return json.dumps(value)


@dataclass(frozen=True)
class ComposedSpec:
    """What a composed version is made from: its entries' installs, the core, Python, and the resolution date."""

    environment: str
    entries: tuple[RegistryEntry, ...]
    core: tuple[tuple[str, str], ...]
    platform: str
    python_version: str
    resolved_at: datetime.datetime

    @classmethod
    def of(
        cls,
        spec: EnvironmentSpec,
        manifest: Manifest,
        composition: Composition,
        resolved_at: datetime.datetime,
        entries: list[str] | None = None,
    ) -> "ComposedSpec":
        """The environment's own entries (``entries`` names another set, for a mash-up), resolved at ``resolved_at``.
        `KeyError` for an entry the manifest does not have."""
        by_id = {e.id: e for e in manifest.entries}
        chosen = entries if entries is not None else spec.entries
        utc = resolved_at.astimezone(datetime.UTC) if resolved_at.tzinfo else resolved_at.replace(tzinfo=datetime.UTC)
        return cls(
            environment=spec.name,
            entries=tuple(by_id[entry_id] for entry_id in chosen),
            core=tuple(sorted(composition.core.items())),
            platform=composition.platform,
            python_version=spec.python_version or DEFAULT_PYTHON_VERSION,
            resolved_at=utc.replace(microsecond=0),
        )

    @property
    def types(self) -> list[str]:
        """The type tables the runner registers, from every entry, in order."""
        return [t for entry in self.entries for t in entry.types]

    def as_json(self) -> dict[str, Any]:
        """The spec as a version records it."""
        return {
            "entries": [
                {
                    "id": e.id,
                    "install": e.install.model_dump(exclude_defaults=True) if e.install else None,
                    "conda": e.conda,
                }
                for e in self.entries
            ],
            "core": dict(self.core),
            "platform": self.platform,
            "python": self.python_version,
            "types": self.types,
        }


def pixi_toml(spec: ComposedSpec) -> str:
    """The pixi workspace for ``spec``: conda-forge for Python and what entries need from it, PyPI and git for the rest,
    every PyPI release exact and every git source at its commit, nothing newer than ``resolved_at``. ``INDEX_ONLY``
    tools come from the index whatever a git package's own sources say."""
    conda: dict[str, str] = {"python": f"{spec.python_version}.*"}
    pypi: dict[str, Any] = {name: f"=={version}" for name, version in spec.core}
    for entry in spec.entries:
        conda.update(entry.conda)
        install = entry.install
        if install is None:
            continue
        if install.git is not None:
            source: dict[str, Any] = {"git": install.git, "rev": install.commit}
        elif install.url is not None:
            # the hash rides in the URL, so the lock (and the version's identity) carries it; the build checks it
            source = {"url": f"{install.url}#sha256={install.sha256}"}
        else:
            source = {"version": f"=={install.version}"}
        if install.extras:
            source["extras"] = install.extras
        pypi[install.name] = source if len(source) > 1 or install.git or install.url else source["version"]
    lines = [
        "[workspace]",
        f"name = {_toml(spec.environment)}",
        'channels = ["conda-forge"]',
        f"platforms = {_toml([spec.platform])}",
        f"exclude-newer = {_toml(spec.resolved_at.strftime('%Y-%m-%dT%H:%M:%SZ'))}",
        "",
        "[dependencies]",
        *(f"{_toml(name)} = {_toml(value)}" for name, value in conda.items()),
        "",
        "[pypi-dependencies]",
        *(f"{_toml(name)} = {_toml(value)}" for name, value in pypi.items()),
        "",
    ]
    index_only = [name for name in INDEX_ONLY if name not in pypi]
    if index_only:
        lines += [
            "[pypi-options.dependency-overrides]",
            *(f"{_toml(name)} = {_toml('>=0')}" for name in index_only),
            "",
        ]
    return "\n".join(lines)


@dataclass(frozen=True)
class PixiLock:
    """A composed version's lock: ``pixi.lock`` as the lock Job wrote it. Its hash is the version's lock identity."""

    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


# Where the build puts the files a composed definition copies in (``build_k8s.build_job``'s ``files``): they are not in
# the definition itself, which Apptainer reads one section at a time and refuses past 64 KiB a section (a pixi.lock
# is larger). The definition records each file's sha256 instead, so its hash still changes exactly when they do.
BUILD_FILES = "/work/files"
TOML_FILE, LOCK_FILE, RUNNER_FILE = "pixi.toml", "pixi.lock", "runner.py"

_TEMPLATE = """\
Bootstrap: docker
From: {pixi_image}

%labels
    org.biosimulations.compose.pixi-toml.sha256 {toml_sha256}
    org.biosimulations.compose.pixi-lock.sha256 {lock_sha256}
    org.biosimulations.compose.runner.sha256 {runner_sha256}

%files
    {files}/{toml_file} {workspace}/pixi.toml
    {files}/{lock_file} {workspace}/pixi.lock
    {files}/{runner_file} {runner}

%post

# pixi installs a git source with the git executable, which the pixi image lacks
apt-get update
apt-get install -y --no-install-recommends git ca-certificates
rm -rf /var/lib/apt/lists/*
{url_checks}cd {workspace}
# exactly the lock: --frozen never re-solves
pixi install --frozen
pixi shell-hook --frozen > {shell_hook}
rm -rf /root/.cache/rattler /root/.cache/uv

%environment
export COMPOSE_RUNNER_TYPES={types}
# wheels that link libpython (libroadrunner) find conda-forge's here: the wheel carries no rpath to it
export LD_LIBRARY_PATH={workspace}/.pixi/envs/default/lib${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}
# the image is read-only under --compat: caches and temporary files go to /tmp
export TMPDIR=/tmp MPLCONFIGDIR=/tmp XDG_CACHE_HOME=/tmp

%runscript
# run by /bin/sh, which has no `source`: pixi's activation is a bash script
exec /bin/bash -c 'source {shell_hook} && exec python {runner} "$@"' runner "$@"
"""


# A wheel installed by URL (composition 7c-2): pixi checks no hash for a direct URL, neither when it locks nor when it
# installs, so the build fetches each one first and checks it against the sha256 its entry gave (carried in the lock as
# the URL's fragment). Only a lock with such a wheel gets these lines, so every other definition is unchanged.
_URL_WHEEL = re.compile(r"^- pypi: direct\+(https://[^\s#]+\.whl)#sha256=([0-9a-f]{64})$", re.MULTILINE)
_URL_CHECKS = """\
# wheels by URL: pixi checks no hash of its own, so each is checked against its entry's sha256 before installing
apt-get update
apt-get install -y --no-install-recommends curl
rm -rf /var/lib/apt/lists/*
{checks}"""
_URL_CHECK = """\
curl -fsSL '{url}' -o /tmp/url.whl || exit 1
echo '{sha256}  /tmp/url.whl' | sha256sum -c - || {{ echo 'sha256 mismatch: {url}' >&2; exit 1; }}
rm -f /tmp/url.whl
"""


def url_wheels(lock: PixiLock) -> list[tuple[str, str]]:
    """Every wheel the lock installs by URL, with the sha256 its entry gave: (url, sha256), in lock order."""
    return [(m.group(1), m.group(2)) for m in _URL_WHEEL.finditer(lock.text)]


def _url_checks(lock: PixiLock) -> str:
    wheels = url_wheels(lock)
    if not wheels:
        return ""
    return _URL_CHECKS.format(checks="".join(_URL_CHECK.format(url=url, sha256=sha) for url, sha in wheels))


def _terminated(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def runner_source() -> str:
    """compose-api's runner as it is now: a composed version records it when it is created, and builds with that."""
    from compose_api.environments import runner

    return _terminated(Path(runner.__file__).read_text())


def composed_files(toml: str, lock: PixiLock, runner: str) -> dict[str, str]:
    """The files a composed definition copies in, by name under ``BUILD_FILES``."""
    return {TOML_FILE: _terminated(toml), LOCK_FILE: _terminated(lock.text), RUNNER_FILE: _terminated(runner)}


def composed_definition(spec: ComposedSpec, lock: PixiLock, pixi_image: str) -> ContainerizationFileRepr:
    """The definition of a composed version made from ``spec`` and locked as ``lock``, built from ``pixi_image``."""
    return definition_of(pixi_toml(spec), spec.types, lock, pixi_image, runner_source())


def definition_of(
    toml: str, types: list[str], lock: PixiLock, pixi_image: str, runner: str
) -> ContainerizationFileRepr:
    """The definition from what a composed version records: its workspace, its runner types, its lock, its image, and
    the runner it was made with (its files are built beside it: ``composed_files``)."""
    files = composed_files(toml, lock, runner)
    representation = _TEMPLATE.format(
        pixi_image=pixi_image,
        toml_sha256=_sha256(files[TOML_FILE]),
        lock_sha256=_sha256(files[LOCK_FILE]),
        runner_sha256=_sha256(files[RUNNER_FILE]),
        files=BUILD_FILES,
        toml_file=TOML_FILE,
        lock_file=LOCK_FILE,
        runner_file=RUNNER_FILE,
        workspace=WORKSPACE,
        shell_hook=SHELL_HOOK,
        runner=RUNNER,
        types=json.dumps(",".join(types)),
        url_checks=_url_checks(lock),
    )
    return ContainerizationFileRepr(
        representation=representation, containerization_engine=ContainerizationEngine.APPTAINER
    )
