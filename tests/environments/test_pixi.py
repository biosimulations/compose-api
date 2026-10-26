"""Composed environments as pixi (docs/plan-environment-composition.md, step 3): the workspace generated from entries,
the definition that installs its lock, and the unprivileged Job that locks it, its script run in bash against a
stand-in for pixi."""

import base64
import datetime
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from compose_api.environments import pixi
from compose_api.environments.pixi import ComposedSpec, PixiLock, composed_definition, pixi_toml
from compose_api.registry.environments import Composition, load_environments
from compose_api.registry.manifest import Manifest, RegistryEntry, load_manifest
from compose_api.simulation import build_k8s
from compose_api.simulation.build_k8s import BuildSite, LockFailedError, lock_job, lock_script, read_inspection_log

SITE = BuildSite(
    namespace="ns", image="ghcr.io/apptainer/apptainer:1.3.6", pvc_claim="home", pvc_mount_path="/projects/CRBM",
    pvc_sub_path="", run_as_uid=16997, run_as_gid=10000, supplemental_groups=(), timeout_seconds=600,
)  # fmt: skip
WHEN = datetime.datetime(2026, 10, 25, 22, 0, 5, 123, tzinfo=datetime.UTC)
COMPOSITION = Composition(pixi_image="ghcr.io/prefix-dev/pixi@sha256:" + "a" * 64, core={"process-bigraph": "1.9.1"})


def _registry_env() -> ComposedSpec:
    environments = load_environments()
    spec = next(e for e in environments.environments if e.name == "registry_env")
    assert environments.composition is not None
    return ComposedSpec.of(spec, load_manifest(), environments.composition, WHEN)


def test_registry_env_becomes_a_pixi_workspace_pinned_to_releases_and_commits() -> None:
    toml = pixi_toml(_registry_env())
    assert 'exclude-newer = "2026-10-25T22:00:05Z"' in toml  # nothing newer than the resolution date, to the second
    assert 'platforms = ["linux-64"]' in toml
    assert '"python" = "3.12.*"' in toml and '"readdy" = "==2.0.13"' in toml  # conda-forge
    assert '"process-bigraph" = "==1.9.1"' in toml and '"bigraph-schema" = "==1.8.1"' in toml  # the common core
    assert '"pbsim-common" = { "git" = "https://github.com/biosimulations/pbsim_common", "rev" = "26fa156c' in toml
    assert '"pyvcell" = { "version" = "==0.5.2", "extras" = ["native", "ode"] }' in toml
    assert '"tellurium" = "==2.2.13.1"' in toml and '"libvcell" = "==0.0.24"' in toml
    assert toml.index("[dependencies]") < toml.index("[pypi-dependencies]")


def test_a_spec_records_its_entries_and_the_runner_types_they_declare() -> None:
    spec = _registry_env()
    recorded = spec.as_json()
    assert recorded["core"] == {"bigraph-schema": "1.8.1", "process-bigraph": "1.9.1"}
    assert recorded["types"] == ["pbsim_common:standard_types"]
    by_id = {e["id"]: e for e in recorded["entries"]}
    assert by_id["readdy"] == {"id": "readdy", "install": None, "conda": {"readdy": "==2.0.13"}}
    assert by_id["pyvcell"]["install"] == {"pypi": "pyvcell", "version": "0.5.2", "extras": ["native", "ode"]}


def test_a_mash_up_names_its_own_entries_and_an_unknown_one_is_refused() -> None:
    environments = load_environments()
    spec = next(e for e in environments.environments if e.name == "registry_env")
    manifest = Manifest(
        entries=[
            RegistryEntry.model_validate({
                "id": "emitters",
                "package": "viva-emitters",
                "source": "https://example.org",
                "version": "0.4.2",
                "module_roots": ["viva_emitters"],
                "level": "tested",
                "install": {"pypi": "viva-emitters", "version": "0.4.2"},
            })
        ]
    )
    mash_up = ComposedSpec.of(spec, manifest, COMPOSITION, WHEN, entries=["emitters"])
    assert '"viva-emitters" = "==0.4.2"' in pixi_toml(mash_up)
    with pytest.raises(KeyError):
        ComposedSpec.of(spec, manifest, COMPOSITION, WHEN, entries=["ghost"])


def test_the_definition_installs_the_lock_frozen_and_runs_the_runner() -> None:
    spec = _registry_env()
    definition = composed_definition(spec, PixiLock("version: 7\n"), COMPOSITION.pixi_image).representation
    assert definition.startswith(f"Bootstrap: docker\nFrom: {COMPOSITION.pixi_image}\n")
    assert "pixi install --frozen" in definition and "pixi lock" not in definition  # installs, never re-solves
    assert "<<'COMPOSE_API_PIXI_LOCK'\nversion: 7\nCOMPOSE_API_PIXI_LOCK\n" in definition
    assert pixi_toml(spec) in definition
    assert "def run(path: Path, output: Path, interval: float)" in definition  # the runner, written in whole
    assert 'export COMPOSE_RUNNER_TYPES="pbsim_common:standard_types"' in definition
    assert "apt-get install -y --no-install-recommends git" in definition  # git sources need the executable
    assert f"LD_LIBRARY_PATH={pixi.WORKSPACE}/.pixi/envs/default/lib" in definition  # libroadrunner finds libpython
    assert definition.rstrip().endswith(f'exec python {pixi.RUNNER} "$@"')
    other = composed_definition(spec, PixiLock("version: 7\n# another\n"), COMPOSITION.pixi_image).representation
    assert other != definition  # the lock is in the definition, so its hash is the version's identity


def test_the_lock_job_runs_pixi_unprivileged_with_nothing_mounted() -> None:
    job: Any = lock_job("lock-abc-x", SITE, COMPOSITION.pixi_image, "[workspace]\n")
    spec = job.spec.template.spec
    (container,) = spec.containers
    assert container.image == COMPOSITION.pixi_image
    assert container.security_context.privileged is False and container.security_context.run_as_user == 16997
    assert container.security_context.allow_privilege_escalation is False
    assert spec.automount_service_account_token is False
    assert [v.name for v in spec.volumes] == ["scratch"] and spec.volumes[0].empty_dir is not None
    env = {e.name: e.value for e in container.env}
    assert base64.b64decode(env[build_k8s.PIXI_TOML_ENV]).decode() == "[workspace]\n"
    assert job.metadata.labels["compose-api-build"] == "lock-abc-x"


@pytest.fixture
def stand_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, str]]:
    """Scratch for the script, and a PATH whose `pixi lock` writes a lock unless the workspace asks for a conflict."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "pixi"
    fake.write_text(
        '#!/bin/bash\n[ "$1" = lock ] || exit 2\n'
        'if grep -q conflict pixi.toml; then echo "  x No solution: a==1 conflicts with a==2" >&2; exit 1; fi\n'
        'printf "version: 7\\nplatforms: []\\n" > pixi.lock\n'
    )
    fake.chmod(0o755)
    monkeypatch.setattr(build_k8s, "SCRATCH_DIR", str(scratch))
    return scratch, {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}


def _lock(stand_in: tuple[Path, dict[str, str]], toml: str) -> dict[str, str]:
    _, env = stand_in
    env = {**env, build_k8s.PIXI_TOML_ENV: base64.b64encode(toml.encode()).decode()}
    result = subprocess.run(  # noqa: S603 the Job's script, rendered from test constants
        ["/bin/bash", "-c", lock_script()], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return read_inspection_log(result.stdout)


def test_the_lock_script_prints_the_lock_or_why_it_did_not_resolve(stand_in: tuple[Path, dict[str, str]]) -> None:
    assert _lock(stand_in, "[workspace]\n") == {build_k8s.LOCKED: "version: 7\nplatforms: []\n"}
    refused = _lock(stand_in, "# conflict\n")
    assert list(refused) == [build_k8s.LOCK_ERROR] and "a==1 conflicts with a==2" in refused[build_k8s.LOCK_ERROR]


class FakeBuilds:
    def __init__(self, log: str) -> None:
        self.log = log
        self.created: list[Any] = []

    def create(self, job: Any) -> None:
        self.created.append(job)

    def state(self, name: str) -> tuple[str, str]:
        return "completed", ""

    def container_log(self, name: str, container: str) -> str:
        return self.log


@pytest.mark.asyncio
async def test_locking_returns_the_lock_or_explains_the_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = build_k8s.INSPECT_MARKER
    monkeypatch.setattr(BuildSite, "from_settings", classmethod(lambda cls, s: SITE))
    for log, expected in [
        (f"{marker} pixi.lock\nversion: 7\n\n{marker} end\n", "version: 7\n"),
        (f"{marker} lock.err\nNo solution: a==1 conflicts\n{marker} end\n", LockFailedError("a==1 conflicts")),
        ("killed\n", RuntimeError("without a lock")),
    ]:
        builds = FakeBuilds(log)
        monkeypatch.setattr(build_k8s, "k8s_builds", lambda b=builds: b)
        if isinstance(expected, Exception):
            with pytest.raises(type(expected), match=str(expected)):
                await build_k8s.lock_composed("[workspace]\n", COMPOSITION.pixi_image, "abcde", poll_seconds=0)
        else:
            assert await build_k8s.lock_composed("[workspace]\n", COMPOSITION.pixi_image, "abcde", poll_seconds=0) == (
                expected
            )
        assert builds.created[0].metadata.name.startswith("lock-")
