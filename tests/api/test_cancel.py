"""``DELETE /simulations/{id}`` (cancel-simulation): who may cancel, what each state answers, and a real SLURM job
cancelled end to end. Withdrawing a queued run, and its races with the worker, are in
tests/simulation/test_submission_worker.py."""

import asyncio
import tempfile
import uuid
from collections.abc import AsyncGenerator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from compose_api.api.main import app
from compose_api.authorization import Caller, get_caller
from compose_api.common.hpc.models import SlurmJob
from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.dependencies import get_simulation_service, set_simulation_service
from compose_api.simulation import handlers
from compose_api.simulation.hpc_utils import _namespace_path
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import JobStatus, JobType, SimulationRequest, SimulatorVersion, Visibility
from compose_api.simulation.simulation_service import SimulationService, SimulationServiceHpc
from tests.fixtures.mocks import TestBackgroundTask
from tests.fixtures.slurm_fixtures_backend import SlurmBackend


@dataclass(frozen=True)
class FakeCaller:
    subject: str
    roles: frozenset[str] = field(default_factory=lambda: frozenset({"user"}))


ALICE, BOB = FakeCaller("auth0|alice"), FakeCaller("auth0|bob")


@pytest_asyncio.fixture
async def http() -> AsyncGenerator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_caller, None)


def _as(caller: Caller | None) -> None:
    async def override() -> Caller | None:
        return caller

    app.dependency_overrides[get_caller] = override


@pytest.mark.asyncio
async def test_cancelling_needs_a_signed_in_caller_who_may_read_the_simulation(
    http: AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:  # fmt: skip
    sim_db = database_service.get_simulator_db()
    public = await sim_db.insert_simulation(
        sim_request=simulation_request, experiment_id="experiment-cancel-public", simulator_version=simulator
    )
    private = await sim_db.insert_simulation(
        sim_request=simulation_request,
        experiment_id="experiment-cancel-private",
        simulator_version=simulator,
        owner_sub=ALICE.subject,
        visibility=Visibility.PRIVATE,
    )
    try:
        _as(None)
        r = await http.delete(f"/simulations/{public.database_id}")
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        _as(BOB)
        assert (await http.delete(f"/simulations/{private.database_id}")).status_code == 404
        assert (await http.delete("/simulations/987654321")).status_code == 404
    finally:
        for sim in (public, private):
            await sim_db.delete_simulation(sim.database_id)


@pytest.mark.asyncio
async def test_a_finished_run_is_not_cancelled(
    http: AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:  # fmt: skip
    sim_db, hpc_db = database_service.get_simulator_db(), database_service.get_hpc_db()
    sim = await sim_db.insert_simulation(
        sim_request=simulation_request, experiment_id="experiment-cancel-done", simulator_version=simulator
    )
    run = await hpc_db.insert_hpcrun(
        slurmjobid=7101, job_type=JobType.SIMULATION, ref_id=sim.database_id, correlation_id="corr-cancel-done"
    )
    done = SlurmJob(job_id=7101, name="n", account="a", user_name="u", job_state="COMPLETED")
    await hpc_db.update_hpcrun_status(run.database_id, done)
    try:
        _as(ALICE)
        r = await http.delete(f"/simulations/{sim.database_id}")
        assert r.status_code == 409 and "already finished (completed)" in r.json()["detail"]
    finally:
        await hpc_db.delete_hpcrun(run.database_id)
        await sim_db.delete_simulation(sim.database_id)


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_cancelling_a_running_simulation_cancels_its_slurm_job(
    http: AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, slurm_backend: SlurmBackend, slurm_service: SlurmService,
    simulation_service_slurm: SimulationServiceHpc, job_monitor: JobMonitor, slurm_template_hello_TEMPLATE: str,
) -> None:  # fmt: skip
    """A real job on the selected backend: the route scancels it, and the job monitor records what SLURM reports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        local = Path(tmpdir) / f"cancel_{uuid.uuid4().hex}.sbatch"
        local.write_text(slurm_template_hello_TEMPLATE.replace("SLEEP_TIME", "50"))
        job_id = await slurm_service._submit_canary_job(
            local_sbatch_file=local, remote_sbatch_file=_namespace_path() / "htclogs" / local.name
        )
    sim_db, hpc_db = database_service.get_simulator_db(), database_service.get_hpc_db()
    sim = await sim_db.insert_simulation(
        sim_request=simulation_request, experiment_id=f"experiment-cancel-{job_id}", simulator_version=simulator
    )
    run = await hpc_db.insert_hpcrun(
        slurmjobid=job_id, job_type=JobType.SIMULATION, ref_id=sim.database_id, correlation_id=f"corr-cancel-{job_id}"
    )
    try:
        _as(ALICE)
        r = await http.delete(f"/simulations/{sim.database_id}")
        assert r.status_code == 202, r.text
        assert r.json() == {"simulation_id": sim.database_id, "withdrawn": False, "slurm_job_id": job_id}

        status = None
        for _ in range(60):  # the monitor polls every 2 s
            current = await hpc_db.get_hpcrun(run.database_id)
            status = current.status if current is not None else None
            if status == JobStatus.CANCELLED:
                break
            await asyncio.sleep(1)
        assert status == JobStatus.CANCELLED
        (reported,) = await slurm_service.get_job_status_sacct(job_ids=[job_id])
        assert JobStatus(reported.job_state.lower()) == JobStatus.CANCELLED

        again = await http.delete(f"/simulations/{sim.database_id}")
        assert again.status_code == 409 and "already finished (cancelled)" in again.json()["detail"]
    finally:
        await slurm_service.cancel_job(job_id)  # idempotent; leaves nothing running if an assertion failed
        await hpc_db.delete_hpcrun(run.database_id)
        await sim_db.delete_simulation(sim.database_id)


@pytest.fixture
def staged_locally(tmp_path: Path) -> Iterator[Path]:
    with override_settings(submission_staging_dir=str(tmp_path / "staging")):
        yield tmp_path / "staging"


async def _queued(database_service: DatabaseServiceSQL, simulation_request: SimulationRequest) -> int:
    experiment = await handlers.run_simulation(
        simulation_request=simulation_request,
        database_service=database_service,
        simulation_service_slurm=cast(SimulationService, None),
        job_monitor=cast(JobMonitor, None),
        background_tasks=TestBackgroundTask(),
    )
    return experiment.simulation_database_id


@pytest.mark.asyncio
async def test_a_queued_run_is_withdrawn_through_the_route_and_a_second_cancel_is_refused(
    http: AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest,
    simulator: SimulatorVersion, staged_locally: Path,
) -> None:  # fmt: skip
    simulation_id = await _queued(database_service, simulation_request)
    _as(ALICE)
    r = await http.delete(f"/simulations/{simulation_id}")
    assert r.status_code == 202, r.text
    assert r.json() == {"simulation_id": simulation_id, "withdrawn": True, "slurm_job_id": None}
    listed = await http.get(f"/simulations/{simulation_id}")
    assert listed.json()["status"] == "cancelled"
    assert ALICE.subject not in listed.text, "who cancelled is not published"
    again = await http.delete(f"/simulations/{simulation_id}")
    assert again.status_code == 409 and "already finished (cancelled)" in again.json()["detail"]


@pytest.mark.asyncio
async def test_a_run_being_submitted_is_a_409_through_the_route(
    http: AsyncClient, database_service: DatabaseServiceSQL, async_postgres_engine: AsyncEngine,
    simulation_request: SimulationRequest, simulator: SimulatorVersion, staged_locally: Path,
) -> None:  # fmt: skip
    simulation_id = await _queued(database_service, simulation_request)
    async with async_postgres_engine.begin() as conn:
        await conn.execute(text(f"UPDATE submission SET state = 'submitting' WHERE simulation_id = {simulation_id}"))  # noqa: S608
    _as(ALICE)
    r = await http.delete(f"/simulations/{simulation_id}")
    assert r.status_code == 409 and "being submitted" in r.json()["detail"]


class _UnreachableCluster:
    """The SSH side failing, as a real scancel over a dropped connection does (only the transport is replaced)."""

    async def cancel_simulation_job(self, slurmjobid: int) -> None:
        raise OSError("ssh: connection reset")


@pytest.mark.asyncio
async def test_a_scancel_that_cannot_reach_slurm_is_a_502(
    http: AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:  # fmt: skip
    sim_db, hpc_db = database_service.get_simulator_db(), database_service.get_hpc_db()
    sim = await sim_db.insert_simulation(
        sim_request=simulation_request, experiment_id="experiment-cancel-502", simulator_version=simulator
    )
    run = await hpc_db.insert_hpcrun(
        slurmjobid=7201, job_type=JobType.SIMULATION, ref_id=sim.database_id, correlation_id="corr-cancel-502"
    )
    saved = get_simulation_service()
    set_simulation_service(cast(SimulationService, _UnreachableCluster()))
    try:
        _as(ALICE)
        r = await http.delete(f"/simulations/{sim.database_id}")
        assert r.status_code == 502 and "try again" in r.json()["detail"]
    finally:
        set_simulation_service(saved)
        await hpc_db.delete_hpcrun(run.database_id)
        await sim_db.delete_simulation(sim.database_id)
