"""Choosing environment versions, step 5 (docs/plan-environment-versions.md): references parsed, resolved to numbers
(a default to its number when the run is recorded), versions runs cannot use refused, a run recording the version it
ran in, and a suite run that must name its versions."""

import uuid
from collections.abc import AsyncGenerator
from typing import cast

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport

from compose_api.api.routers import suites as suites_router
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.db.services.environments_db import VersionSource
from compose_api.environments.versions import (
    VersionUnavailableError,
    parse_version_refs,
    resolve_versions,
    version_for,
)
from compose_api.simulation import handlers
from compose_api.simulation.containerization import ContainerizationEngine, ContainerizationFileRepr
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import EnvironmentVersion, SimulationRequest, VersionState
from compose_api.simulation.simulation_service import SimulationService
from tests.fixtures.mocks import TestBackgroundTask

SHARED = "registry_env"


async def _another_version(database_service: DatabaseServiceSQL, state: VersionState) -> EnvironmentVersion:
    """A new version of the shared environment, of a definition of its own, in ``state``."""
    definition = ContainerizationFileRepr(
        representation=f"Bootstrap: docker\nFrom: busybox\n# {uuid.uuid4().hex}\n",
        containerization_engine=ContainerizationEngine.APPTAINER,
    )
    simulator = await database_service.get_simulator_db().insert_simulator(definition)
    environments_db = database_service.get_environments_db()
    version, _ = await environments_db.create_version(SHARED, "shared", simulator.database_id, VersionSource())
    await environments_db.set_state(version.database_id, state)
    return version.model_copy(update={"state": state})


@pytest.mark.parametrize(
    ("refs", "expected"),
    [
        (None, (False, {})),
        (["default"], (True, {})),
        (["registry_env@2"], (False, {"registry_env": 2})),
        (["registry_env@default", "viva-pde-particle@7"], (False, {"registry_env": None, "viva-pde-particle": 7})),
    ],
)
def test_references_are_environment_at_number_or_default(
    refs: list[str] | None, expected: tuple[bool, dict[str, int | None]]
) -> None:
    assert parse_version_refs(refs) == expected


@pytest.mark.parametrize("refs", [["registry_env"], ["@2"], ["registry_env@two"], ["registry_env@1", "registry_env@2"]])
def test_a_malformed_or_repeated_reference_is_refused(refs: list[str]) -> None:
    with pytest.raises(ValueError, match=r"registry_env|environment@number"):
        parse_version_refs(refs)


@pytest.mark.asyncio
async def test_references_resolve_to_numbers_and_unusable_versions_are_refused(
    database_service: DatabaseServiceSQL,
) -> None:
    default, _ = await version_for(database_service, None)
    building = await _another_version(database_service, VersionState.BUILDING)
    retired = await _another_version(database_service, VersionState.RETIRED)
    failed = await _another_version(database_service, VersionState.FAILED)
    used = {SHARED}

    assert await resolve_versions(database_service, ["default"], used, require_all=True) == {SHARED: default.number}
    assert await resolve_versions(database_service, [f"{SHARED}@default"], used, require_all=True) == {
        SHARED: default.number
    }
    chosen = await resolve_versions(database_service, [f"{SHARED}@{building.number}"], used, require_all=True)
    assert chosen == {SHARED: building.number}  # a version still building is waited for, like any image
    assert await resolve_versions(database_service, None, used, require_all=False) == {}  # default when recorded

    for refs, why in [
        (None, "name a version of registry_env"),
        ([f"{SHARED}@{retired.number}"], "retired"),
        ([f"{SHARED}@{failed.number}"], "failed"),
        ([f"{SHARED}@99999"], "no version"),
        (["viva-pde-particle@1"], "do not use viva-pde-particle"),
    ]:
        with pytest.raises(VersionUnavailableError, match=why):
            await resolve_versions(database_service, refs, used, require_all=True)


@pytest.mark.asyncio
async def test_a_run_naming_a_version_runs_in_it_and_is_labelled_with_it(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest
) -> None:
    chosen = await _another_version(database_service, VersionState.READY)
    experiment = await handlers.run_simulation(
        simulation_request=simulation_request.model_copy(update={"environment_version": chosen.number}),
        database_service=database_service,
        simulation_service_slurm=cast(SimulationService, None),  # used only by the submission worker
        job_monitor=cast(JobMonitor, None),
        background_tasks=TestBackgroundTask(),
    )
    assert experiment.simulator_database_id == chosen.simulator_id
    row = await database_service.get_simulator_db().get_simulation_row(experiment.simulation_database_id)
    assert row is not None
    assert row.simulation.environment_version_id == chosen.database_id
    assert row.simulation.labels["environment_version"] == chosen.label

    default, _ = await version_for(database_service, None)
    unnamed = await handlers.run_simulation(
        simulation_request=simulation_request,
        database_service=database_service,
        simulation_service_slurm=cast(SimulationService, None),
        job_monitor=cast(JobMonitor, None),
        background_tasks=TestBackgroundTask(),
    )
    row = await database_service.get_simulator_db().get_simulation_row(unnamed.simulation_database_id)
    assert row is not None and row.simulation.labels["environment_version"] == default.label


@pytest_asyncio.fixture
async def suites_client(database_service: DatabaseServiceSQL) -> AsyncGenerator[httpx.AsyncClient]:
    app = FastAPI()
    app.include_router(suites_router.config.router, prefix=suites_router.config.prefix)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_a_suite_run_must_name_its_versions_and_records_them_as_numbers(
    suites_client: httpx.AsyncClient, database_service: DatabaseServiceSQL
) -> None:
    default, _ = await version_for(database_service, None)
    assert (await suites_client.post("/suites/smoke/run")).status_code == 422  # required

    started = await suites_client.post("/suites/smoke/run", params={"environment_version": "default"})
    assert started.status_code == 200, started.text
    assert started.json()["environment_versions"] == {SHARED: default.number}
    number = started.json()["number"]
    listed = (await suites_client.get("/suites/smoke/runs")).json()
    assert next(r for r in listed if r["number"] == number)["environment_versions"] == {SHARED: default.number}

    refused = await suites_client.post("/suites/smoke/run", params={"environment_version": f"{SHARED}@99999"})
    assert refused.status_code == 400 and "no version" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_a_renamed_environment_keeps_its_versions_runs_and_suite_runs(
    suites_client: httpx.AsyncClient, database_service: DatabaseServiceSQL, simulation_request: SimulationRequest
) -> None:
    """Everything refers to an environment by id: after a rename, its versions, a run recorded in one, and a suite
    run that named one all resolve under the new name; the old name finds nothing."""
    chosen = await _another_version(database_service, VersionState.READY)
    experiment = await handlers.run_simulation(
        simulation_request=simulation_request.model_copy(update={"environment_version": chosen.number}),
        database_service=database_service,
        simulation_service_slurm=cast(SimulationService, None),
        job_monitor=cast(JobMonitor, None),
        background_tasks=TestBackgroundTask(),
    )
    started = await suites_client.post("/suites/smoke/run", params={"environment_version": f"{SHARED}@{chosen.number}"})
    assert started.status_code == 200, started.text
    number = started.json()["number"]
    environments_db = database_service.get_environments_db()
    renamed = f"renamed-{uuid.uuid4().hex[:8]}"
    await environments_db.rename(SHARED, renamed)
    try:
        moved = await environments_db.get_by_number(renamed, chosen.number)
        assert moved is not None and moved.database_id == chosen.database_id
        assert moved.environment == renamed and moved.environment_id == chosen.environment_id
        assert await environments_db.get_by_number(SHARED, chosen.number) is None
        row = await database_service.get_simulator_db().get_simulation_row(experiment.simulation_database_id)
        assert row is not None and row.simulation.environment_version_id == chosen.database_id
        listed = (await suites_client.get("/suites/smoke/runs")).json()
        assert next(r for r in listed if r["number"] == number)["environment_versions"] == {renamed: chosen.number}
    finally:
        await environments_db.rename(renamed, SHARED)
