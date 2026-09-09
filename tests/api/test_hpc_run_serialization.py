"""
Pins the JSON wire format of an ``HpcRun`` served by ``/results/simulation/status``.

FastAPI 0.130 switched JSON response serialization from ``jsonable_encoder`` + stdlib ``json`` to
pydantic-core whenever a ``response_model`` is set. pbest parses this payload with the published
``compose-api-client``, so any drift in field names, enum values, null handling, or the datetime
string format must show up here first, not in pbest.
"""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr

from compose_api.common.hpc.models import SlurmJob
from compose_api.db.database_service import DatabaseService
from compose_api.simulation.models import JobType, SimulationFileType, SimulationRequest

_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "resources" / "hpc_run_response.json"

_SLURM_JOB_ID = 424242
_CORRELATION_ID = "hpc-run-round-trip-fixture"
_EXPERIMENT_ID = "hpc-run-round-trip-experiment"
_START_TIME = "2026-01-02T03:04:05"
_END_TIME = "2026-01-02T03:14:05"


@pytest.mark.asyncio
async def test_hpc_run_status_matches_json_fixture(
    fastapi_app: FastAPI, local_base_url: str, database_service: DatabaseService
) -> None:
    simulator_db = database_service.get_simulator_db()
    hpc_db = database_service.get_hpc_db()

    container_def = ContainerizationFileRepr(
        representation="Bootstrap: docker\nFrom: python:3.14-slim\n# hpc-run round-trip fixture\n",
        containerization_engine=ContainerizationEngine.APPTAINER,
    )
    simulator = await simulator_db.insert_simulator(container_def, packages_used=None)
    simulation = await simulator_db.insert_simulation(
        sim_request=SimulationRequest(
            request_file_path=Path("fixture.omex"), simulation_file_type=SimulationFileType.OMEX, is_batch=False
        ),
        experiment_id=_EXPERIMENT_ID,
        simulator_version=simulator,
    )
    hpc_run = await hpc_db.insert_hpcrun(
        slurmjobid=_SLURM_JOB_ID,
        job_type=JobType.SIMULATION,
        ref_id=simulation.database_id,
        correlation_id=_CORRELATION_ID,
    )
    try:
        # Pin every mutable field so the response is fully deterministic apart from database ids.
        await hpc_db.update_hpcrun_status(
            hpc_run.database_id,
            SlurmJob(
                job_id=_SLURM_JOB_ID,
                name="round-trip",
                account="test",
                user_name="test",
                job_state="COMPLETED",
                start_time=_START_TIME,
                end_time=_END_TIME,
            ),
        )

        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url=local_base_url) as client:
            response = await client.get("/results/simulation/status", params={"simulation_id": simulation.database_id})

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"

        expected = json.loads(_FIXTURE_PATH.read_text())
        expected["database_id"] = hpc_run.database_id
        expected["sim_id"] = simulation.database_id

        actual = response.json()
        assert actual == expected
        # Key order is part of what pydantic-core emits; keep it aligned with the model declaration.
        assert list(actual) == list(expected)
    finally:
        await hpc_db.delete_hpcrun(hpc_run.database_id)
        await simulator_db.delete_simulation(simulation.database_id)
        await simulator_db.delete_simulator(simulator.database_id)
