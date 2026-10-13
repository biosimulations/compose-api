"""A container definition is built once, however many runs need it at the same moment, and a failed build is tried
again rather than taken as done (simulations 4578 and 4579: a SED-ML comparison's two runs, submitted together with a
new registry_env definition; one built and failed, the other skipped the build and ran without an image)."""

import asyncio
import uuid

import pytest
from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr

from compose_api.common.hpc.models import SlurmJob
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation import handlers
from compose_api.simulation.models import JobStatus, JobType, SimulatorVersion


class NoDownload:
    async def download_container(self, image: object) -> None:
        raise RuntimeError("not published")


@pytest.mark.asyncio
async def test_concurrent_runs_build_once_and_a_failed_build_is_retried(
    database_service: DatabaseServiceSQL, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = ContainerizationFileRepr(
        representation=f"Bootstrap: docker\nFrom: busybox\n# {uuid.uuid4().hex}\n",
        containerization_engine=ContainerizationEngine.APPTAINER,
    )
    simulator: SimulatorVersion = await database_service.get_simulator_db().insert_simulator(definition)
    hpc_db = database_service.get_hpc_db()
    builds: list[str] = []
    outcome = {"state": "FAILED"}

    async def build(simulator_version: SimulatorVersion, hpc_db: object, random_prefix: str, **_: object) -> None:
        builds.append(random_prefix)
        await asyncio.sleep(0.2)  # the other run arrives while this one builds
        run = await database_service.get_hpc_db().insert_hpcrun(
            slurmjobid=7000 + len(builds), job_type=JobType.BUILD_CONTAINER, ref_id=simulator.database_id,
            correlation_id=f"build-{uuid.uuid4().hex[:8]}",
        )  # fmt: skip
        await database_service.get_hpc_db().update_hpcrun_status(
            run.database_id, SlurmJob(job_id=7000 + len(builds), name="b", account="a", user_name="u",
                                      job_state=outcome["state"]),
        )  # fmt: skip
        if outcome["state"] == "FAILED":
            raise RuntimeError("the build failed")

    monkeypatch.setattr(handlers, "_build_container_and_wait", build)

    async def dispatch(name: str) -> BaseException | None:
        try:
            await handlers._download_or_build_container(NoDownload(), simulator, hpc_db, None, name)  # type: ignore[arg-type]
        except RuntimeError as e:
            return e
        return None

    # two runs at once: the first builds (and fails), the second waits, then retries the failed build itself
    outcome["state"] = "FAILED"
    first = await asyncio.gather(dispatch("a"), dispatch("b"))
    assert builds == ["a", "b"] and all(isinstance(e, RuntimeError) for e in first)

    # a build that completes is reused by every later run
    outcome["state"] = "COMPLETED"
    await asyncio.gather(dispatch("c"), dispatch("d"))
    assert builds == ["a", "b", "c"]
    latest = await hpc_db.get_hpcrun_by_ref(ref_id=simulator.database_id, job_type=JobType.BUILD_CONTAINER)
    assert latest is not None and latest.status == JobStatus.COMPLETED
