"""Simulators' images are artifacts (docs/plan-environment-builds.md, phase 2): "built" means an available record,
checked against the file on the store; an unrecorded file is adopted, a missing one marked unavailable, and a build or
pull that leaves no file is a failure rather than a silent success."""

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr

from compose_api.config import get_settings, override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation import handlers, images
from compose_api.simulation.models import HpcRun, ImageKind, JobType, SimulatorVersion


@pytest.fixture
def mount(tmp_path: Path) -> Iterator[Path]:
    """The API's mount of the store, with the namespace's images directory: the namespace's own, and the store's base
    as the session has it (the SLURM backend fixture sets it for the whole session), or a stand-in when unset."""
    root = tmp_path / "mount"
    (root / get_settings().namespace / "images").mkdir(parents=True)
    base = {} if get_settings().simulation_store_base_path else {"simulation_store_base_path": "/store/compose_api"}
    with override_settings(internal_mount_dir=str(root), **base):
        yield root


async def _simulator(database_service: DatabaseServiceSQL) -> SimulatorVersion:
    definition = ContainerizationFileRepr(
        representation=f"Bootstrap: docker\nFrom: busybox\n# {uuid.uuid4().hex}\n",
        containerization_engine=ContainerizationEngine.APPTAINER,
    )
    return await database_service.get_simulator_db().insert_simulator(definition)


def _sif(mount: Path, simulator: SimulatorVersion) -> Path:
    return mount / get_settings().namespace / "images" / f"{simulator.container_def_hash}.sif"


@pytest.mark.asyncio
async def test_an_unrecorded_image_is_adopted_and_a_missing_one_marked_unavailable(
    database_service: DatabaseServiceSQL, mount: Path
) -> None:
    simulator_db = database_service.get_simulator_db()
    simulator = await _simulator(database_service)
    assert await images.available_sif(simulator_db, simulator) is None  # no file, no record

    _sif(mount, simulator).write_bytes(b"sif bytes")
    adopted = await images.available_sif(simulator_db, simulator)
    assert adopted is not None
    settings = get_settings()
    assert adopted.location == (
        f"{settings.simulation_store_base_path}/{settings.namespace}/images/{simulator.container_def_hash}.sif"
    )
    assert adopted.digest == "sha256:" + hashlib.sha256(b"sif bytes").hexdigest()
    assert adopted.size_bytes == len(b"sif bytes") and adopted.hpcrun_id is None
    again = await images.available_sif(simulator_db, simulator)
    assert again is not None and again.database_id == adopted.database_id

    _sif(mount, simulator).unlink()
    assert await images.available_sif(simulator_db, simulator) is None
    [record] = await simulator_db.list_images(simulator.database_id)
    assert record.database_id == adopted.database_id and not record.available


@pytest.mark.asyncio
async def test_images_are_write_once(database_service: DatabaseServiceSQL) -> None:
    simulator_db = database_service.get_simulator_db()
    simulator = await _simulator(database_service)
    first = await simulator_db.record_image(simulator.database_id, ImageKind.SIF, "/x.sif", digest="sha256:a")
    same = await simulator_db.record_image(simulator.database_id, ImageKind.SIF, "/x.sif", digest="sha256:a")
    assert same.database_id == first.database_id

    changed = await simulator_db.record_image(simulator.database_id, ImageKind.SIF, "/x.sif", digest="sha256:b")
    assert changed.database_id != first.database_id
    records = {r.database_id: r for r in await simulator_db.list_images(simulator.database_id)}
    assert not records[first.database_id].available and records[changed.database_id].available
    available = await simulator_db.get_available_image(simulator.database_id, ImageKind.SIF)
    assert available is not None and available.digest == "sha256:b"


class _Service:
    """Pulls write nothing; builds write the file when ``writes`` is set."""

    def __init__(self, mount: Path, database_service: DatabaseServiceSQL, pull_ok: bool, writes: bool) -> None:
        self.mount, self.database_service, self.pull_ok, self.writes = mount, database_service, pull_ok, writes

    async def download_container(self, image: object) -> None:
        if not self.pull_ok:
            raise RuntimeError("not published")


@pytest.mark.asyncio
@pytest.mark.parametrize("writes", [True, False])
async def test_a_build_records_its_image_or_fails_without_one(
    database_service: DatabaseServiceSQL, mount: Path, monkeypatch: pytest.MonkeyPatch, writes: bool
) -> None:
    simulator = await _simulator(database_service)
    hpc_db = database_service.get_hpc_db()

    async def build(simulator_version: SimulatorVersion, **_: object) -> HpcRun:
        run = await hpc_db.insert_hpcrun(
            slurmjobid=None, job_type=JobType.BUILD_CONTAINER, ref_id=simulator_version.database_id,
            correlation_id=f"build-{uuid.uuid4().hex[:8]}", backend="k8s", external_id="build-job",
        )  # fmt: skip
        if writes:
            _sif(mount, simulator_version).write_bytes(b"built")
        return run

    monkeypatch.setattr(handlers, "_build_container_and_wait", build)
    service = _Service(mount, database_service, pull_ok=False, writes=writes)
    simulator_db = database_service.get_simulator_db()

    async def dispatch() -> None:
        await handlers._download_or_build_container(
            cast(Any, service), simulator, hpc_db, cast(Any, None), "r", simulator_db=simulator_db
        )

    if not writes:
        with pytest.raises(RuntimeError, match="completed without writing"):
            await dispatch()
        assert await simulator_db.get_available_image(simulator.database_id, ImageKind.SIF) is None
        return
    await dispatch()
    image = await simulator_db.get_available_image(simulator.database_id, ImageKind.SIF)
    build_run = await hpc_db.get_hpcrun_by_ref(ref_id=simulator.database_id, job_type=JobType.BUILD_CONTAINER)
    assert image is not None and build_run is not None and image.hpcrun_id == build_run.database_id
    assert image.digest == "sha256:" + hashlib.sha256(b"built").hexdigest()


@pytest.mark.asyncio
async def test_a_pull_that_leaves_no_file_fails(database_service: DatabaseServiceSQL, mount: Path) -> None:
    simulator = await _simulator(database_service)
    service = _Service(mount, database_service, pull_ok=True, writes=False)
    with pytest.raises(RuntimeError, match="left no image"):
        await handlers._download_or_build_container(
            cast(Any, service),
            simulator,
            database_service.get_hpc_db(),
            cast(Any, None),
            "r",
            simulator_db=database_service.get_simulator_db(),
        )


@pytest.mark.asyncio
async def test_verification_adopts_and_counts(database_service: DatabaseServiceSQL, mount: Path) -> None:
    simulator_db = database_service.get_simulator_db()
    present, absent = await _simulator(database_service), await _simulator(database_service)
    _sif(mount, present).write_bytes(b"present")
    await images.verify_images(simulator_db)
    assert await simulator_db.get_available_image(present.database_id, ImageKind.SIF) is not None
    assert await simulator_db.get_available_image(absent.database_id, ImageKind.SIF) is None
