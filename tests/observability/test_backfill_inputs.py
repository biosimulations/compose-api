"""The one-off backfill registers the input of runs that predate the job script's ``announce_input``."""

import hashlib
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from compose_api.common.gateway.models import Namespace
from compose_api.common.hpc.models import SlurmJob
from compose_api.config import get_settings, override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.db.services.datasets_db import DatasetQuery
from compose_api.observability.backfill_inputs import backfill_inputs
from compose_api.simulation.hpc_utils import get_internal_experiment_dir
from compose_api.simulation.models import JobStatus, JobType, SimulationRequest, SimulatorVersion


async def _ran(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion, n: int
) -> tuple[int, str]:
    experiment_id = f"exp-backfill-{n}"
    simulation = await database_service.get_simulator_db().insert_simulation(
        sim_request=simulation_request, experiment_id=experiment_id, simulator_version=simulator
    )
    run = await database_service.get_hpc_db().insert_hpcrun(
        slurmjobid=95000 + n, job_type=JobType.SIMULATION, ref_id=simulation.database_id, correlation_id=f"bf-{n}"
    )
    await database_service.get_hpc_db().update_hpcrun_status(
        run.database_id,
        SlurmJob(job_id=95000 + n, name="x", account="a", user_name="u", job_state=JobStatus.COMPLETED.value),
    )
    return simulation.database_id, experiment_id


@pytest.mark.asyncio
async def test_inputs_on_the_store_are_registered_once(
    database_service: DatabaseServiceSQL,
    async_postgres_engine: AsyncEngine,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
    tmp_path: Path,
) -> None:
    with override_settings(internal_mount_dir=str(tmp_path)):
        with_input, experiment_id = await _ran(database_service, simulation_request, simulator, 1)
        without_input, _ = await _ran(database_service, simulation_request, simulator, 2)
        directory = get_internal_experiment_dir(experiment_id, Namespace(get_settings().namespace))
        directory.mkdir(parents=True)
        (directory / f"{experiment_id}.pbg").write_bytes(b'{"state": {}}')

        registered, not_found = await backfill_inputs(async_postgres_engine, database_service)
        assert registered >= 1 and not_found >= 1

        datasets, _ = await database_service.get_datasets_db().page(DatasetQuery(simulation_id=with_input))
        (dataset,) = [d for d in datasets if d.kind == "input"]
        assert (dataset.path, dataset.media_type) == (f"{experiment_id}.pbg", "application/json")
        assert dataset.sha256 == hashlib.sha256(b'{"state": {}}').hexdigest()
        assert dataset.attributes == {"file_type": "pbg"}
        missing, _ = await database_service.get_datasets_db().page(DatasetQuery(simulation_id=without_input))
        assert missing == []

        # Repeating it registers nothing new for a simulation that has its input.
        await backfill_inputs(async_postgres_engine, database_service)
        again, _ = await database_service.get_datasets_db().page(DatasetQuery(simulation_id=with_input))
        assert [d.id for d in again] == [dataset.id]
