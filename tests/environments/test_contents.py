"""Reading back what an environment version's image installed and provides (docs/plan-environment-versions.md, V7,
step 4b): the build Job's scripts, run in bash against a scratch directory with a stand-in for apptainer; the Job's
shape; and storing what they wrote on the version."""

import json
import os
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from compose_api.api.routers import registry as registry_router
from compose_api.config import get_settings, override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.environments.contents import record_contents
from compose_api.environments.versions import version_for
from compose_api.simulation import build_k8s
from compose_api.simulation.build_k8s import BuildSite, Inspection, build_job, inspect_script, publish_script
from compose_api.simulation.models import VersionState

SITE = BuildSite(
    namespace="ns", image="ghcr.io/apptainer/apptainer:1.3.6", pvc_claim="home", pvc_mount_path="/projects/CRBM",
    pvc_sub_path="", run_as_uid=16997, run_as_gid=10000, supplemental_groups=(), timeout_seconds=600,
)  # fmt: skip

# a describe script stand-in: prints what it was asked for, as the real one prints a manifest
DESCRIBE = "import json, sys\nprint(json.dumps({'schema_version': 'pbg-interfaces/1', 'argv': sys.argv[1:]}))\n"
INSPECTION = Inspection(
    python=("python3",), roots=("pbsim_common", "biosim_toolkit"), environment="registry_env", label="registry_env@2",
    describe_script=DESCRIBE,
)  # fmt: skip


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, dict[str, str]]]:
    """A scratch directory for the scripts' /work, and a PATH whose apptainer runs the command it is given."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "image.sif").write_bytes(b"sif")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    apptainer = bin_dir / "apptainer"
    apptainer.write_text('#!/bin/bash\n[ "$1" = exec ] || exit 2\nshift 4\nexec "$@"\n')  # exec --bind DIR SIF ...
    apptainer.chmod(0o755)
    monkeypatch.setattr(build_k8s, "WORK_DIR", str(work))
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOSTNAME": "pod"}
    yield work, env


def _bash(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # the scripts the build Job runs, rendered by build_k8s from test constants
    return subprocess.run(  # noqa: S603
        ["/bin/bash", "-c", "set -eu\n" + script], env=env, capture_output=True, text=True, check=False
    )


def test_the_build_lists_the_images_packages_and_describes_its_interfaces(work: tuple[Path, dict[str, str]]) -> None:
    root, env = work
    env = {**env, build_k8s.DESCRIBE_ENV: _b64(DESCRIBE)}
    result = _bash(inspect_script(INSPECTION), env)
    assert result.returncode == 0, result.stderr
    installed = (root / "image.installed.txt").read_text().splitlines()
    assert any(line.startswith("pytest==") for line in installed)  # this interpreter's own distributions
    assert installed == sorted(installed, key=str.lower)
    described = json.loads((root / "image.interfaces.json").read_text())
    assert described["argv"] == [
        "pbsim_common",
        "biosim_toolkit",
        "--env-name",
        "registry_env",
        "--image",
        "registry_env@2",
    ]


def test_reading_back_never_fails_the_build(work: tuple[Path, dict[str, str]]) -> None:
    root, env = work
    failing = Inspection(python=("false",), roots=("x",), environment="e", label="e@1", describe_script="")
    result = _bash(inspect_script(failing), {**env, build_k8s.DESCRIBE_ENV: _b64("raise SystemExit(1)")})
    assert result.returncode == 0, result.stderr
    assert "could not list the installed packages" in result.stderr
    assert "could not describe the interfaces" in result.stderr
    assert not (root / "image.installed.txt").exists() and not (root / "image.interfaces.json").exists()
    without_script = _bash(inspect_script(INSPECTION), env)  # no describe script in the Job: packages only
    assert without_script.returncode == 0 and not (root / "image.interfaces.json").exists()


def test_the_copy_places_what_was_read_beside_the_image(work: tuple[Path, dict[str, str]], tmp_path: Path) -> None:
    root, env = work
    (root / "image.installed.txt").write_text("six==1.10.0\n")  # the interfaces were not written
    images = tmp_path / "store" / "images"
    container = images / "abc.sif"
    targets = {"installed.txt": images / "abc.installed.txt", "interfaces.json": images / "abc.interfaces.json"}
    result = _bash(publish_script(container, targets), env)
    assert result.returncode == 0, result.stderr
    assert container.read_bytes() == b"sif"
    assert targets["installed.txt"].read_text() == "six==1.10.0\n"
    assert not targets["interfaces.json"].exists()
    assert sorted(p.name for p in images.iterdir()) == ["abc.installed.txt", "abc.sif"]  # no partial files left


def test_the_job_carries_the_describe_script_and_copies_beside_the_image() -> None:
    container = Path("/projects/CRBM/compose_api/prod/images/abc.sif")
    job: Any = build_job("build-abc-x", SITE, "Bootstrap: docker\nFrom: busybox\n", container, INSPECTION)
    (build,) = job.spec.template.spec.init_containers
    (copy,) = job.spec.template.spec.containers
    env = {e.name: e.value for e in build.env}
    assert _unb64(env[build_k8s.DESCRIBE_ENV]) == DESCRIBE
    assert "apptainer exec --bind /work /work/image.sif python3 /work/installed.py" in build.command[-1]
    assert build.command[-1].index("apptainer build") < build.command[-1].index("apptainer exec")
    assert "abc.installed.txt" in copy.command[-1] and "abc.interfaces.json" in copy.command[-1]
    plain: Any = build_job("build-abc-x", SITE, "Bootstrap: docker\nFrom: busybox\n", container)
    assert "apptainer exec" not in plain.spec.template.spec.init_containers[0].command[-1]
    assert "installed.txt" not in plain.spec.template.spec.containers[0].command[-1]


def test_the_reread_job_reads_a_built_image_again_without_exposing_the_store_to_the_privileged_container() -> None:
    container = Path("/projects/CRBM/compose_api/prod/images/abc.sif")
    job: Any = build_k8s.reread_job("reread-abc-x", SITE, container, INSPECTION)
    spec = job.spec.template.spec
    fetch, inspect = spec.init_containers
    (copy,) = spec.containers
    # the service user copies the image in, reading the store only
    assert fetch.security_context.privileged is False and fetch.security_context.run_as_user == 16997
    assert [(m.name, m.read_only) for m in fetch.volume_mounts] == [("shared", True), ("work", None)]
    assert f'cp "{container}" /work/image.sif' in fetch.command[-1]
    # the privileged container sees the work volume only, and runs the build's own read-back
    assert inspect.security_context.privileged is True
    assert [m.name for m in inspect.volume_mounts] == ["work"]
    assert inspect.command[-1].endswith(inspect_script(INSPECTION))
    assert "apptainer build" not in inspect.command[-1]
    assert _unb64({e.name: e.value for e in inspect.env}[build_k8s.DESCRIBE_ENV]) == DESCRIBE
    # and the service user places what was read beside the image, never the image itself
    assert "abc.installed.txt" in copy.command[-1] and "abc.interfaces.json" in copy.command[-1]
    assert "image.sif" not in copy.command[-1]


def test_the_reread_job_scripts_leave_what_they_read_beside_the_image(
    work: tuple[Path, dict[str, str]], tmp_path: Path
) -> None:
    from compose_api.simulation.hpc_utils import get_slurm_singularity_container_file

    root, env = work
    (root / "image.sif").unlink()
    with override_settings(simulation_store_base_path=str(tmp_path / "store")):
        container = get_slurm_singularity_container_file("abc")
        job: Any = build_k8s.reread_job("reread-abc-x", SITE, container, INSPECTION)
    images = container.parent
    images.mkdir(parents=True)
    container.write_bytes(b"sif")
    fetch, inspect = job.spec.template.spec.init_containers
    (copy,) = job.spec.template.spec.containers
    for step, extra in ((fetch, {}), (inspect, {build_k8s.DESCRIBE_ENV: _b64(DESCRIBE)}), (copy, {})):
        result = _bash(step.command[-1], {**env, **extra})
        assert result.returncode == 0, result.stderr
    assert container.read_bytes() == b"sif"
    assert (images / "abc.installed.txt").read_text().strip()
    assert json.loads((images / "abc.interfaces.json").read_text())["argv"][:2] == ["pbsim_common", "biosim_toolkit"]


@pytest.mark.asyncio
async def test_what_the_build_left_is_stored_on_the_version_when_it_is_read(
    database_service: DatabaseServiceSQL, tmp_path: Path
) -> None:
    name = "viva-pde-particle"  # listed in environments.yaml, so its routes answer
    image = f"ghcr.io/example/s@sha256:{uuid.uuid4().hex}{uuid.uuid4().hex}"
    root = tmp_path / "mount"
    base = {} if get_settings().simulation_store_base_path else {"simulation_store_base_path": "/store/compose_api"}
    with override_settings(prebuilt_simulators={name: image}, internal_mount_dir=str(root), **base):
        version, simulator = await version_for(database_service, name)
        images = root / get_settings().namespace / "images"
        images.mkdir(parents=True)
        assert not await record_contents(database_service, version)  # the build left nothing yet

        (images / f"{simulator.container_def_hash}.installed.txt").write_text("six==1.10.0\n")
        (images / f"{simulator.container_def_hash}.interfaces.json").write_text('{"components": []}')
        app = FastAPI()
        app.include_router(registry_router.config.router, prefix=registry_router.config.prefix)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            detail = (await client.get(f"/registry/environments/{name}/versions/{version.number}")).json()
    assert (detail["installed"], detail["interfaces"]) == ("six==1.10.0\n", {"components": []})
    stored = await database_service.get_environments_db().get_by_number(name, version.number)
    assert stored is not None and stored.installed == "six==1.10.0\n"


def _b64(text: str) -> str:
    import base64

    return base64.b64encode(text.encode()).decode()


def _unb64(text: str) -> str:
    import base64

    return base64.b64decode(text).decode()


# --- prebuilt images, read by a Job of their own (step 4c) ---------------------------------------------------------


def test_a_prebuilt_image_prints_what_it_holds_between_markers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(build_k8s, "SCRATCH_DIR", str(scratch))
    env = {**os.environ, build_k8s.INSTALLED_ENV: _b64(build_k8s._INSTALLED), build_k8s.DESCRIBE_ENV: _b64(DESCRIBE)}
    result = _bash(build_k8s.prebuilt_inspect_script(INSPECTION), env)
    assert result.returncode == 0, result.stderr
    files = build_k8s.read_inspection_log(result.stdout)
    assert any(line.startswith("pytest==") for line in files["installed.txt"].splitlines())
    assert json.loads(files["interfaces.json"])["argv"][-2:] == ["--image", "registry_env@2"]

    failing = Inspection(python=("false",), roots=("x",), environment="e", label="e@1", describe_script="")
    quiet = _bash(build_k8s.prebuilt_inspect_script(failing), env)
    assert quiet.returncode == 0 and build_k8s.read_inspection_log(quiet.stdout) == {}


def test_only_a_log_that_reached_its_end_is_read() -> None:
    marker = build_k8s.INSPECT_MARKER
    log = f"noise\n{marker} installed.txt\nsix==1.10.0\n\n{marker} interfaces.json\n{{}}\n\n{marker} end\n"
    assert build_k8s.read_inspection_log(log) == {"installed.txt": "six==1.10.0\n", "interfaces.json": "{}\n"}
    assert build_k8s.read_inspection_log(log.removesuffix(f"{marker} end\n")) == {}  # cut off: nothing trusted


def test_the_inspection_job_runs_the_image_unprivileged_with_nothing_mounted() -> None:
    image = f"ghcr.io/example/pde@sha256:{'a' * 64}"
    job: Any = build_k8s.inspection_job("inspect-aaaa-x", SITE, image, INSPECTION)
    spec = job.spec.template.spec
    (container,) = spec.containers
    assert container.image == image and not spec.init_containers
    assert container.security_context.privileged is False and container.security_context.run_as_user == 16997
    assert container.security_context.allow_privilege_escalation is False
    assert spec.automount_service_account_token is False
    assert [v.name for v in spec.volumes] == ["scratch"] and spec.volumes[0].empty_dir is not None
    env = {e.name: _unb64(e.value) for e in container.env}
    assert env == {build_k8s.INSTALLED_ENV: build_k8s._INSTALLED, build_k8s.DESCRIBE_ENV: DESCRIBE}
    assert job.metadata.labels["compose-api-build"] == "inspect-aaaa-x"  # where its log is found


@pytest.mark.asyncio
async def test_a_prebuilt_version_is_read_back_after_it_is_ready_and_on_request(
    database_service: DatabaseServiceSQL, monkeypatch: pytest.MonkeyPatch
) -> None:
    from compose_api.authorization import get_caller
    from compose_api.simulation import handlers

    @dataclass(frozen=True)
    class Admin:
        subject: str = "auth0|ops"
        roles: frozenset[str] = frozenset({"user", "env-admin"})

    inspected: list[str] = []
    reread: list[str] = []

    async def reread_shared(singularity_hash: str, inspection: Inspection, suffix: str) -> bool:
        reread.append(singularity_hash)
        return True

    async def inspect_prebuilt(image: str, inspection: Inspection, suffix: str) -> dict[str, str]:
        inspected.append(image)
        return {"installed.txt": "dolfinx==0.9.0\n", "interfaces.json": '{"components": [1]}'}

    async def ensure_image(*_: object, **__: object) -> None:
        return None

    async def no_script() -> None:
        return None

    monkeypatch.setattr(build_k8s, "inspect_prebuilt", inspect_prebuilt)
    monkeypatch.setattr(build_k8s, "reread_shared", reread_shared)
    monkeypatch.setattr(build_k8s, "describe_script", no_script)
    monkeypatch.setattr(handlers, "ensure_image", ensure_image)
    from compose_api import dependencies

    for name in ("get_required_simulation_service", "get_required_job_monitor"):
        monkeypatch.setattr(registry_router, name, lambda: None)
        monkeypatch.setattr(dependencies, name, lambda: None)  # the version's build (environments/lifecycle.py)
    app = FastAPI()
    app.include_router(registry_router.config.router, prefix=registry_router.config.prefix)

    async def admin() -> Admin:
        return Admin()

    app.dependency_overrides[get_caller] = admin
    image = f"ghcr.io/example/pde@sha256:{uuid.uuid4().hex}{uuid.uuid4().hex}"
    base = "/registry/environments/viva-pde-particle/versions"
    with override_settings(environment_admin_role="env-admin", build_backend="k8s"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            number = (await client.post(base, json={"image": image})).json()["number"]
            detail = (await client.get(f"{base}/{number}")).json()
            assert (detail["state"], detail["installed"], detail["interfaces"]) == (
                "ready", "dolfinx==0.9.0\n", {"components": [1]}
            )  # fmt: skip
            again = await client.post(f"{base}/{number}/inspect")
            assert again.status_code == 202
            assert inspected == [image, image]
            assert reread == []  # a prebuilt image is pulled and run, not read from the store
            # a shared version built before builds read images back is read again from its built image
            shared, simulator = await version_for(database_service, None)
            await database_service.get_environments_db().set_state(shared.database_id, VersionState.READY)
            again = await client.post(f"/registry/environments/registry_env/versions/{shared.number}/inspect")
            assert again.status_code == 202
            assert reread == [simulator.container_def_hash]
            # one still building is read back by its build
            await database_service.get_environments_db().set_state(shared.database_id, VersionState.BUILDING)
            refused = await client.post(f"/registry/environments/registry_env/versions/{shared.number}/inspect")
            assert refused.status_code == 409
            await database_service.get_environments_db().set_state(shared.database_id, VersionState.READY)
    with override_settings(environment_admin_role="env-admin", build_backend="slurm"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            assert (await client.post(f"{base}/{number}/inspect")).status_code == 409  # no Kubernetes to run it on


@pytest.mark.asyncio
async def test_a_composed_version_is_read_back_through_pixis_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    from compose_api.environments import pixi
    from compose_api.simulation.models import EnvironmentVersion

    async def no_script() -> None:
        return None

    monkeypatch.setattr(build_k8s, "describe_script", no_script)
    version = EnvironmentVersion(
        database_id=1, environment_id=1, environment="registry_env", number=3, state=VersionState.READY,
        simulator_id=9, runtime_contract=pixi.RUNTIME_CONTRACT,
    )  # fmt: skip
    composed = await build_k8s.inspection_of(version)
    shared = await build_k8s.inspection_of(version.model_copy(update={"runtime_contract": 1}))
    assert composed is not None and composed.python == pixi.PYTHON
    assert shared is not None and shared.python[0] == "micromamba"  # @1, built the old way, keeps its own


@pytest.mark.asyncio
async def test_the_read_back_records_what_the_generic_checks_find_using_the_images_type_tables(
    database_service: DatabaseServiceSQL, tmp_path: Path
) -> None:
    name = "viva-pde-particle"  # its module root is viva_pde_particle
    image = f"ghcr.io/example/s@sha256:{uuid.uuid4().hex}{uuid.uuid4().hex}"
    root = tmp_path / "mount"
    base = {} if get_settings().simulation_store_base_path else {"simulation_store_base_path": "/store/compose_api"}
    interfaces = {
        "components": [
            {
                "name": "Utc",
                "kind": "step",
                "module": "viva_pde_particle.steps",
                "outputs": {"result": "numeric_result"},
            },
            {"name": "Ok", "kind": "step", "module": "viva_pde_particle.steps", "outputs": {"x": "overwrite[float]"}},
        ]
    }
    types = {"numeric_result": {"time": "list[float]", "values": "list[list[float]]"}}
    with override_settings(prebuilt_simulators={name: image}, internal_mount_dir=str(root), **base):
        version, simulator = await version_for(database_service, name)
        images = root / get_settings().namespace / "images"
        images.mkdir(parents=True)
        (images / f"{simulator.container_def_hash}.interfaces.json").write_text(json.dumps(interfaces))
        (images / f"{simulator.container_def_hash}.types.json").write_text(json.dumps(types))
        assert await record_contents(database_service, version)
    stored = await database_service.get_environments_db().get_by_number(name, version.number)
    assert stored is not None and stored.findings is not None
    (finding,) = stored.findings
    assert finding["component"] == "viva_pde_particle.steps.Utc" and finding["severity"] == "fail"
    assert "result.time: list[float] (appends)" in finding["detail"]


def test_the_type_tables_are_read_by_a_script_that_shadows_no_standard_module() -> None:
    script = inspect_script(INSPECTION)
    assert "/type_tables.py" in script and "/types.py" not in script  # `types` would shadow the standard module
