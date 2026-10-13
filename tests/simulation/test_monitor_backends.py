"""The monitor asks each backend about its own runs (docs/plan-environment-builds.md, E1, E2): SLURM runs through
squeue and sacct as before, a run on another backend through that backend's poller, by its external id."""

import uuid

import pytest
from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr

from compose_api.common.hpc.models import SlurmJob
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import JobStatus, JobType


class FakeSlurm:
    def __init__(self) -> None:
        self.asked: list[list[int]] = []

    async def get_job_status_squeue(self, job_ids: list[int]) -> list[SlurmJob]:
        self.asked.append(job_ids)
        return [SlurmJob(job_id=j, name="s", account="a", user_name="u", job_state="COMPLETED") for j in job_ids]

    async def get_job_status_sacct(self, job_ids: list[int]) -> list[SlurmJob]:
        return []


class FakeK8s:
    def __init__(self) -> None:
        self.asked: list[list[str]] = []

    async def states(self, external_ids: list[str]) -> dict[str, SlurmJob]:
        self.asked.append(external_ids)
        return {i: SlurmJob(job_id=0, name=i, account="k8s", user_name="k8s", job_state="FAILED") for i in external_ids}


@pytest.mark.asyncio
async def test_each_backend_is_polled_for_its_own_runs(database_service: DatabaseServiceSQL) -> None:
    definition = ContainerizationFileRepr(
        representation=f"Bootstrap: docker\nFrom: busybox\n# {uuid.uuid4().hex}\n",
        containerization_engine=ContainerizationEngine.APPTAINER,
    )
    simulator = await database_service.get_simulator_db().insert_simulator(definition)
    hpc_db = database_service.get_hpc_db()
    slurm_run = await hpc_db.insert_hpcrun(
        slurmjobid=8801, job_type=JobType.BUILD_CONTAINER, ref_id=simulator.database_id, correlation_id="b-slurm-8801"
    )
    k8s_run = await hpc_db.insert_hpcrun(
        slurmjobid=None, job_type=JobType.BUILD_CONTAINER, ref_id=simulator.database_id,
        correlation_id="b-k8s-1", backend="k8s", external_id="build-abc-1",
    )  # fmt: skip
    assert (slurm_run.backend, slurm_run.external_id) == ("slurm", "8801")
    assert (k8s_run.backend, k8s_run.external_id) == ("k8s", "build-abc-1")

    slurm, k8s = FakeSlurm(), FakeK8s()
    monitor = JobMonitor(database_service, slurm)  # type: ignore[arg-type]
    unpolled = await hpc_db.insert_hpcrun(
        slurmjobid=None, job_type=JobType.BUILD_CONTAINER, ref_id=simulator.database_id,
        correlation_id="b-k8s-2", backend="k8s", external_id="build-abc-2",
    )  # fmt: skip
    await monitor.update_running_jobs()  # no k8s poller yet: its runs are left alone
    assert (await hpc_db.get_hpcrun(k8s_run.database_id)).status == JobStatus.RUNNING  # type: ignore[union-attr]

    monitor.register_backend("k8s", k8s)
    await monitor.update_running_jobs()
    assert slurm.asked[0] == [8801]  # SLURM is asked about its own runs only
    assert sorted(k8s.asked[-1]) == ["build-abc-1", "build-abc-2"]
    assert (await hpc_db.get_hpcrun(slurm_run.database_id)).status == JobStatus.COMPLETED  # type: ignore[union-attr]
    assert (await hpc_db.get_hpcrun(k8s_run.database_id)).status == JobStatus.FAILED  # type: ignore[union-attr]
    assert (await hpc_db.get_hpcrun(unpolled.database_id)).status == JobStatus.FAILED  # type: ignore[union-attr]
