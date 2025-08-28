import random
import string
from pathlib import Path

import pytest

from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.hpc_utils import get_correlation_id, get_slurm_sim_experiment_dir
from compose_api.simulation.models import (
    Simulation,
    SimulationRequest,
)


@pytest.mark.asyncio
async def test_save_request_to_mongo(database_service: DatabaseServiceSQL) -> None:
    for simulator in await database_service.list_simulators():
        await database_service.delete_simulator(simulator_id=simulator.database_id)

    cache_hash = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure

    # When the server first receives the Omex file it's placed in a temp dir for further processing
    local_path = Path("/tmp/fjdsljkl")  # noqa: S108
    sim_request = SimulationRequest(omex_archive=local_path)

    # insert a document into the database
    sim: Simulation = await database_service.insert_simulation(sim_request, cache_hash)
    assert sim.database_id is not None

    # reread the document from the database
    sim2 = await database_service.get_simulation(sim.database_id)
    assert sim2 is not None

    assert sim.database_id == sim2.database_id
    assert sim.slurmjob_id == sim2.slurmjob_id
    assert sim.pb_cache_hash == sim2.pb_cache_hash
    assert sim.sim_request.omex_archive != sim2.sim_request.omex_archive
    assert sim.sim_request.omex_archive == local_path
    assert sim2.sim_request.omex_archive == get_slurm_sim_experiment_dir(get_correlation_id(sim, cache_hash))

    # delete the document from the database
    await database_service.delete_simulation(sim.database_id)
    sim3 = await database_service.get_simulation(sim.database_id)
    assert sim3 is None
