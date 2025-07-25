import random

import pytest

from biosim_api.simulation.database_service import DatabaseServiceSQL
from biosim_api.simulation.models import (
    Simulation,
    SimulationRequest,
)


@pytest.mark.asyncio
async def test_save_request_to_mongo(database_service: DatabaseServiceSQL) -> None:
    param1_value = random.random()  # noqa: S311 Standard pseudo-random generators are not suitable for cryptographic purposes
    param2_value = random.random()  # noqa: S311 Standard pseudo-random generators are not suitable for cryptographic purposes

    for simulator in await database_service.list_simulators():
        await database_service.delete_simulator(simulator_id=simulator.database_id)

    simulator_version = await database_service.insert_simulator(
        git_commit_hash="9c3d1c8",
        git_repo_url="https://github.com/sim_org/simulator",
        git_branch="main",
    )

    sim_request = SimulationRequest(
        simulator=simulator_version,
        variant_config={
            "named_parameters": {
                "param1": param1_value,
                "param2": param2_value,
            }
        },
    )

    # insert a document into the database
    sim: Simulation = await database_service.insert_simulation(sim_request)
    assert sim.database_id is not None

    # reread the document from the database
    sim2 = await database_service.get_simulation(sim.database_id)
    assert sim2 is not None

    assert sim == sim2

    # delete the document from the database
    await database_service.delete_simulation(sim.database_id)
    sim3 = await database_service.get_simulation(sim.database_id)
    assert sim3 is None
