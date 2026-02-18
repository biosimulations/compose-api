import random
import string
from pathlib import Path

import pytest

from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.hpc_utils import get_experiment_id, get_slurm_sim_experiment_dir
from compose_api.simulation.models import (
    Simulation,
    SimulationFileType,
    SimulationRequest,
    SimulatorVersion,
)


@pytest.mark.asyncio
async def test_save_request_to_mongo(database_service: DatabaseServiceSQL, simulator: SimulatorVersion) -> None:
    # When the server first receives the Omex file it's placed in a temp dir for further processing
    local_path = Path("/tmp/fjdsljkl")  # noqa: S108
    sim_request: SimulationRequest = SimulationRequest(
        request_file_path=local_path, simulation_file_type=SimulationFileType.OMEX
    )

    experiment_id = get_experiment_id(simulator, "".join(random.choices(string.hexdigits, k=7)))  # noqa: S311 doesn't need to be secure

    # insert a document into the database
    sim: Simulation = await database_service.get_simulator_db().insert_simulation(sim_request, experiment_id, simulator)
    assert sim.database_id is not None

    # reread the document from the database
    sim2 = await database_service.get_simulator_db().get_simulation(sim.database_id)
    assert sim2 is not None

    assert sim.database_id == sim2.database_id
    assert sim.sim_request.request_file_path != sim2.sim_content.path_on_server
    assert sim.sim_request.request_file_path == local_path
    assert sim2.sim_content.path_on_server == get_slurm_sim_experiment_dir(experiment_id)

    # delete the document from the database
    await database_service.get_simulator_db().delete_simulation(sim.database_id)
    sim3 = await database_service.get_simulator_db().get_simulation(sim.database_id)
    assert sim3 is None
