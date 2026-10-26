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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr

from compose_api.registry.environments import Composition, EnvironmentSpec
from compose_api.registry.manifest import Manifest, RegistryEntry

RUNTIME_CONTRACT = 2  # compose-api's runner (environments/runner.py) answers the job; a change to it is a new contract
WORKSPACE = "/opt/environment"
RUNNER = "/opt/compose-api/runner.py"
SHELL_HOOK = f"{WORKSPACE}/shell-hook.sh"
# How to enter a composed image's Python: pixi's activation (conda activation scripts, for dolfinx or PETSc) first
PYTHON = ("/bin/bash", "-c", f'source {SHELL_HOOK} && exec python "$@"', "python")
DEFAULT_PYTHON_VERSION = "3.12"


def _toml(value: Any) -> str:
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
    every PyPI release exact and every git source at its commit, nothing newer than ``resolved_at``."""
    conda: dict[str, str] = {"python": f"{spec.python_version}.*"}
    pypi: dict[str, Any] = {name: f"=={version}" for name, version in spec.core}
    for entry in spec.entries:
        conda.update(entry.conda)
        install = entry.install
        if install is None:
            continue
        if install.git is not None:
            source: dict[str, Any] = {"git": install.git, "rev": install.commit}
        else:
            source = {"version": f"=={install.version}"}
        if install.extras:
            source["extras"] = install.extras
        pypi[install.name] = source if len(source) > 1 or install.git else source["version"]
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
    return "\n".join(lines)


@dataclass(frozen=True)
class PixiLock:
    """A composed version's lock: ``pixi.lock`` as the lock Job wrote it. Its hash is the version's lock identity."""

    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


_TEMPLATE = """\
Bootstrap: docker
From: {pixi_image}

%post

# pixi installs a git source with the git executable, which the pixi image lacks
apt-get update
apt-get install -y --no-install-recommends git ca-certificates
rm -rf /var/lib/apt/lists/*
mkdir -p {workspace} {runner_dir}
cd {workspace}
cat > pixi.toml <<'COMPOSE_API_PIXI_TOML'
{toml}COMPOSE_API_PIXI_TOML
cat > pixi.lock <<'COMPOSE_API_PIXI_LOCK'
{lock}COMPOSE_API_PIXI_LOCK
# exactly the lock: --frozen never re-solves
pixi install --frozen
pixi shell-hook --frozen > {shell_hook}
rm -rf /root/.cache/rattler /root/.cache/uv
cat > {runner} <<'COMPOSE_API_RUNNER'
{runner_source}COMPOSE_API_RUNNER

%environment
export COMPOSE_RUNNER_TYPES={types}
# wheels that link libpython (libroadrunner) find conda-forge's here: the wheel carries no rpath to it
export LD_LIBRARY_PATH={workspace}/.pixi/envs/default/lib${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}
# the image is read-only under --compat: caches and temporary files go to /tmp
export TMPDIR=/tmp MPLCONFIGDIR=/tmp XDG_CACHE_HOME=/tmp

%runscript
source {shell_hook}
exec python {runner} "$@"
"""


def _terminated(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def composed_definition(spec: ComposedSpec, lock: PixiLock, pixi_image: str) -> ContainerizationFileRepr:
    """The definition of a composed version made from ``spec`` and locked as ``lock``, built from ``pixi_image``."""
    return definition_of(pixi_toml(spec), spec.types, lock, pixi_image)


def definition_of(toml: str, types: list[str], lock: PixiLock, pixi_image: str) -> ContainerizationFileRepr:
    """The definition from what a composed version records: its workspace, its runner types, its lock, its image."""
    from compose_api.environments import runner

    representation = _TEMPLATE.format(
        pixi_image=pixi_image,
        workspace=WORKSPACE,
        runner_dir=str(Path(RUNNER).parent),
        toml=_terminated(toml),
        lock=_terminated(lock.text),
        shell_hook=SHELL_HOOK,
        runner=RUNNER,
        runner_source=_terminated(Path(runner.__file__).read_text()),
        types=json.dumps(",".join(types)),
    )
    return ContainerizationFileRepr(
        representation=representation, containerization_engine=ContainerizationEngine.APPTAINER
    )
