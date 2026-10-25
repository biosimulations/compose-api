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

    async def inspect_prebuilt(image: str, inspection: Inspection, suffix: str) -> dict[str, str]:
        inspected.append(image)
        return {"installed.txt": "dolfinx==0.9.0\n", "interfaces.json": '{"components": [1]}'}

    async def ensure_image(*_: object, **__: object) -> None:
        return None

    async def no_script() -> None:
        return None

    monkeypatch.setattr(build_k8s, "inspect_prebuilt", inspect_prebuilt)
    monkeypatch.setattr(build_k8s, "describe_script", no_script)
    monkeypatch.setattr(handlers, "ensure_image", ensure_image)
    for name in ("get_required_simulation_service", "get_required_job_monitor"):
        monkeypatch.setattr(registry_router, name, lambda: None)
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
            shared = (await client.get("/registry/environments/registry_env/versions")).json()["versions"]
            if shared:  # a shared version is read back by its build, never by this Job
                refused = await client.post(
                    f"/registry/environments/registry_env/versions/{shared[0]['number']}/inspect"
                )
                assert refused.status_code == 409
    with override_settings(environment_admin_role="env-admin", build_backend="slurm"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            assert (await client.post(f"{base}/{number}/inspect")).status_code == 409  # no Kubernetes to run it on
