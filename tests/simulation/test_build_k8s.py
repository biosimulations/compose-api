"""Container builds as Kubernetes Jobs (compose_api/simulation/build_k8s.py, docs/plan-environment-builds.md phase 3):
the Job's shape; the poller's view of Jobs; and a build end to end against a fake Kubernetes, recorded as a k8s run
the monitor updates, its image recorded as produced by that run."""

import asyncio
import base64
import contextlib
import dataclasses
import gzip
import hashlib
import os
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from compose_api.config import get_settings, override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation import build_k8s, builds, handlers
from compose_api.simulation.build_k8s import BuildSite, K8sPoller, build_job, job_name
from compose_api.simulation.builds import BuildFailedError
from compose_api.simulation.containerization import ContainerizationEngine, ContainerizationFileRepr
from compose_api.simulation.models import ImageKind, JobStatus, JobType

SITE = BuildSite(
    namespace="ns", image="ghcr.io/apptainer/apptainer:1.3.6", pvc_claim="home", pvc_mount_path="/projects/CRBM",
    pvc_sub_path="", run_as_uid=16997, run_as_gid=10000, supplemental_groups=(), timeout_seconds=600,
)  # fmt: skip


def test_the_build_runs_privileged_in_scratch_and_copies_as_the_service_user() -> None:
    definition = "Bootstrap: docker\nFrom: busybox\n%post\n  echo 'it is built'\n"
    container = Path("/projects/CRBM/compose_api/prod/images/abc.sif")
    job: Any = build_job("build-abc-x", SITE, definition, container)
    spec = job.spec.template.spec
    (build,) = spec.init_containers
    (copy,) = spec.containers
    assert build.security_context.privileged is True and build.security_context.run_as_user == 0
    # the privileged container sees scratch only: the definition comes with the Job, not from the shared filesystem
    assert [m.mount_path for m in build.volume_mounts] == ["/work"]
    (env,) = build.env
    assert gzip.decompress(base64.b64decode(env.value)).decode() == definition
    assert f'echo "${env.name}" | base64 -d | gunzip > /work/image.def' in build.command[-1]
    assert "apptainer build /work/image.sif /work/image.def" in build.command[-1]
    # all of the build's scratch (Apptainer's sandbox and cache) is the volume it requests disk for
    assert "export APPTAINER_TMPDIR=/work/scratch APPTAINER_CACHEDIR=/work/cache" in build.command[-1]
    assert build.resources is None  # SITE requests no ephemeral storage
    assert copy.security_context.privileged is False and copy.security_context.run_as_user == 16997
    assert {m.mount_path: m.read_only for m in copy.volume_mounts} == {"/projects/CRBM": None, "/work": None}
    assert f'mv -f "{container}.part-$HOSTNAME" "{container}"' in copy.command[-1]
    assert job.spec.backoff_limit == 0 and spec.restart_policy == "Never"
    assert spec.volumes[0].persistent_volume_claim.claim_name == "home"


def test_the_build_requests_disk_so_it_is_placed_on_a_node_with_room() -> None:
    site = dataclasses.replace(SITE, ephemeral_storage="20Gi")
    job: Any = build_job("build-abc-x", site, "Bootstrap: docker\nFrom: busybox\n", Path("/c"))
    (build,) = job.spec.template.spec.init_containers
    assert build.resources.requests == {"ephemeral-storage": "20Gi"}
    assert build.resources.limits is None  # a request, never a limit: a bigger build is not evicted
    assert BuildSite.from_settings(get_settings().model_copy(update={
        "build_k8s_pvc_claim": "home", "build_k8s_pvc_mount_path": "/projects/CRBM",
    })).ephemeral_storage == "20Gi"  # fmt: skip


class _Gone(Exception):
    status = 404


class FakeK8s:
    """Jobs by name: ``outcome`` is what a Job reports once created; a completed one writes its image first."""

    def __init__(self, outcome: str, sif: Path | None = None) -> None:
        self.outcome, self.sif = outcome, sif
        self.created: list[Any] = []

    def create(self, job: Any) -> None:
        self.created.append(job)
        if self.outcome == "completed" and self.sif is not None:
            self.sif.write_bytes(b"built in k8s")

    def state(self, name: str) -> tuple[str, str]:
        if not any(job.metadata.name == name for job in self.created):
            raise _Gone()
        return self.outcome, "BackoffLimitExceeded" if self.outcome == "failed" else ""

    def logs(self, name: str) -> str:
        return "== pod / build ==\nFATAL: something"


@pytest.mark.asyncio
async def test_the_poller_reports_job_states_and_a_vanished_job_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeK8s("completed")
    fake.created.append(build_job("build-a", SITE, "Bootstrap: docker\nFrom: busybox\n", Path("/c")))
    monkeypatch.setattr(build_k8s, "k8s_builds", lambda: fake)
    states = await K8sPoller().states(["build-a", "build-gone"])
    assert states["build-a"].job_state == "COMPLETED" and states["build-gone"].job_state == "FAILED"


@pytest.fixture
def k8s_site(tmp_path: Path) -> Iterator[Path]:
    """The store as the API mounts it, and build_backend=k8s."""
    root = tmp_path / "mount"
    (root / get_settings().namespace / "images").mkdir(parents=True)
    base = {} if get_settings().simulation_store_base_path else {"simulation_store_base_path": "/store/compose_api"}
    with override_settings(
        internal_mount_dir=str(root), build_backend="k8s", build_k8s_namespace="ns", build_k8s_pvc_claim="home",
        build_k8s_pvc_mount_path="/store", **base,
    ):  # fmt: skip
        yield root


class _NoDownload:
    async def download_container(self, image: object) -> None:
        raise RuntimeError("not published")


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "failed"])
async def test_a_build_is_a_k8s_run_the_monitor_updates_and_its_image_is_recorded(
    outcome: str, database_service: DatabaseServiceSQL, k8s_site: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = ContainerizationFileRepr(
        representation=f"Bootstrap: docker\nFrom: busybox\n# {uuid.uuid4().hex}\n",
        containerization_engine=ContainerizationEngine.APPTAINER,
    )
    simulator_db, hpc_db = database_service.get_simulator_db(), database_service.get_hpc_db()
    simulator = await simulator_db.insert_simulator(definition)
    images_dir = k8s_site / get_settings().namespace / "images"
    fake = FakeK8s(outcome, sif=images_dir / f"{simulator.container_def_hash}.sif")
    monkeypatch.setattr(build_k8s, "k8s_builds", lambda: fake)
    monkeypatch.setattr(builds, "POLL_SECONDS", 0.05)

    async def monitor() -> None:
        """The job monitor's k8s pass: unfinished k8s runs, their Jobs' states written back."""
        poller = K8sPoller()
        while True:
            runs = [r for r in await hpc_db.list_unfinished_hpcruns() if r.backend == "k8s" and r.external_id]
            states = await poller.states([r.external_id for r in runs if r.external_id]) if runs else {}
            for r in runs:
                if r.external_id in states:
                    await hpc_db.update_hpcrun_status(hpcrun_id=r.database_id, new_slurm_job=states[r.external_id])
            await asyncio.sleep(0.05)

    polling = asyncio.create_task(monitor())

    async def dispatch() -> None:
        await handlers._download_or_build_container(
            cast(Any, _NoDownload()), simulator, hpc_db, cast(Any, None), "AbCdE", simulator_db=simulator_db
        )

    try:
        if outcome == "completed":
            await asyncio.wait_for(dispatch(), timeout=30)
        else:
            with pytest.raises(BuildFailedError, match="FATAL: something"):
                await asyncio.wait_for(dispatch(), timeout=30)
    finally:
        polling.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await polling

    (job,) = fake.created
    assert job.metadata.name == job_name(simulator, "AbCdE")
    run = await hpc_db.get_hpcrun_by_ref(ref_id=simulator.database_id, job_type=JobType.BUILD_CONTAINER)
    assert run is not None and run.slurmjobid is None
    assert run.backend == "k8s" and run.external_id == job.metadata.name
    image = await simulator_db.get_available_image(simulator.database_id, ImageKind.SIF)
    if outcome == "completed":
        assert run.status == JobStatus.COMPLETED
        assert image is not None and image.hpcrun_id == run.database_id
    else:
        assert run.status == JobStatus.FAILED and image is None


def test_a_composed_definition_fits_one_environment_string_and_decodes_as_the_job_decodes_it(tmp_path: Path) -> None:
    """A composed version's definition carries its whole pixi.lock (registry_env's: 177 KB as base64), over Linux's
    128 KiB limit for one environment string, which stopped the build container from starting at all
    (`exec /bin/bash: argument list too long`). Gzipped first, it fits, and the Job's own line restores it."""
    lock = "".join(
        f"- pypi: https://files.pythonhosted.org/packages/{i:04d}/pkg-{i}.whl\n  name: pkg{i}\n" for i in range(2500)
    )
    definition = f"Bootstrap: docker\nFrom: busybox\n%post\ncat > pixi.lock <<'L'\n{lock}L\n"
    assert len(base64.b64encode(definition.encode())) > 128 * 1024  # what failed
    encoded = build_k8s.encode_definition(definition)
    assert len(encoded) < 128 * 1024
    assert build_k8s.encode_definition(definition) == encoded  # no timestamp: the same Job each time
    result = subprocess.run(  # noqa: S603 the build script's decoding line, run as the Job runs it
        ["/bin/bash", "-c", f'echo "${build_k8s.DEFINITION_ENV}" | base64 -d | gunzip > {tmp_path}/image.def'],
        env={**os.environ, build_k8s.DEFINITION_ENV: encoded}, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "image.def").read_text() == definition


def test_a_composed_definitions_files_are_carried_in_chunks_and_unpacked_where_it_copies_them_from(
    tmp_path: Path,
) -> None:
    """A composed definition copies its pixi.toml, pixi.lock and runner in from the build's work directory: the Job
    carries them as a gzipped tar, in chunks, each under Linux's limit for one environment string."""
    lock = "".join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(6000)) + "\n"  # barely compresses
    files = {"pixi.lock": lock, "pixi.toml": "[workspace]\n", "runner.py": "print(1)\n"}
    chunks = build_k8s.encode_files(files)
    assert len(chunks) > 1 and all(len(c) <= 96 * 1024 for c in chunks)
    assert build_k8s.encode_files(files) == chunks  # no timestamps: the same Job each time
    job: Any = build_job("build-abc-x", SITE, "Bootstrap: docker\nFrom: busybox\n", Path("/p/abc.sif"), None, files)
    (build,) = job.spec.template.spec.init_containers
    env = {e.name: e.value for e in build.env}
    assert [env[f"{build_k8s.FILES_ENV}{i}"] for i in range(len(chunks))] == chunks
    script = build.command[-1]
    assert script.index("tar -xz -C /work/files") < script.index("apptainer build")
    unpack = build_k8s.unpack_files_script(len(chunks), str(tmp_path / "files"))
    result = subprocess.run(  # noqa: S603 the build script's unpacking lines, run as the Job runs them
        ["/bin/bash", "-c", "set -eu\n" + unpack],
        env={**os.environ, **{f"{build_k8s.FILES_ENV}{i}": c for i, c in enumerate(chunks)}},
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    assert {p.name: p.read_text() for p in (tmp_path / "files").iterdir()} == files
    plain: Any = build_job("build-abc-x", SITE, "Bootstrap: docker\nFrom: busybox\n", Path("/p/abc.sif"))
    assert "tar -xz" not in plain.spec.template.spec.init_containers[0].command[-1]  # other definitions have none
