"""Every run links to where it ran, and every simulator to its runs (docs/plan-webapp-admin.md, step 5c):
``GET /registry/simulators[/{id}]``, and ``GET /simulations`` by simulator, environment and version."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from compose_api.api.main import app
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.models import SimulationRequest, SimulatorVersion, Visibility
from compose_api.simulation.prebuilt import prebuilt_definition
from tests.api.test_authorization import ALICE
from tests.fixtures.postgres_fixtures import register_prebuilt

VERSIONED = "ghcr.io/example/versioned@sha256:" + "1" * 64
EARLIER = "ghcr.io/example/earlier@sha256:" + "2" * 64  # a simulator from before versions: none is its version
UNUSED = "ghcr.io/example/unused@sha256:" + "3" * 64


@dataclass
class Recorded:
    versioned: SimulatorVersion
    earlier: SimulatorVersion
    unused: SimulatorVersion
    number: int
    linked: int  # ran in the version
    unlinked: int  # on the version's simulator, recorded before the version was
    legacy: int
    private: int


@pytest_asyncio.fixture
async def recorded(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest
) -> AsyncGenerator[Recorded]:
    sim_db = database_service.get_simulator_db()
    version = await register_prebuilt(database_service, "viva-pde-particle", VERSIONED)
    versioned = await sim_db.get_simulator(version.simulator_id or 0)
    assert versioned is not None
    earlier = await sim_db.insert_simulator(prebuilt_definition(EARLIER), packages_used=None)
    unused = await sim_db.insert_simulator(prebuilt_definition(UNUSED), packages_used=None)

    async def simulation(
        name: str, simulator: SimulatorVersion, version_id: int | None = None, owner: str | None = None
    ) -> int:
        sim = await sim_db.insert_simulation(
            sim_request=simulation_request,
            experiment_id=f"exp-simulators-{name}",
            simulator_version=simulator,
            environment_version_id=version_id,
            owner_sub=owner,
            visibility=Visibility.PRIVATE if owner else Visibility.PUBLIC,
        )
        return sim.database_id

    found = Recorded(
        versioned=versioned,
        earlier=earlier,
        unused=unused,
        number=version.number,
        linked=await simulation("linked", versioned, version.database_id),
        unlinked=await simulation("unlinked", versioned),
        legacy=await simulation("legacy", earlier),
        private=await simulation("private", earlier, owner=ALICE.subject),
    )
    yield found
    for simulation_id in (found.linked, found.unlinked, found.legacy, found.private):
        await sim_db.delete_simulation(simulation_id)
    for simulator in (versioned, earlier, unused):
        await sim_db.delete_simulator(simulator.database_id)


@pytest.mark.asyncio
async def test_simulators_list_their_versions_and_the_runs_that_used_them(recorded: Recorded) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        listed = {s["simulator_id"]: s for s in (await http.get("/registry/simulators")).json()}
        versioned = listed[recorded.versioned.database_id]
        assert versioned["versions"] == [{"environment": "viva-pde-particle", "number": recorded.number}]
        assert versioned["run_count"] == 2 and versioned["first_run_at"] and versioned["last_run_at"]
        earlier = listed[recorded.earlier.database_id]
        assert earlier["versions"] == [] and earlier["run_count"] == 1  # the private run is not counted
        assert earlier["container_def_hash"] == recorded.earlier.container_def_hash
        assert recorded.unused.database_id not in listed  # neither a version nor used

        detail = (await http.get(f"/registry/simulators/{recorded.earlier.database_id}")).json()
        assert detail["definition"] == recorded.earlier.container_def.representation
        assert detail["run_count"] == 1
        assert (await http.get(f"/registry/simulators/{recorded.unused.database_id}")).status_code == 404
        assert (await http.get("/registry/simulators/987654321")).status_code == 404


@pytest.mark.asyncio
async def test_simulations_name_their_version_and_filter_by_simulator_environment_and_version(
    recorded: Recorded,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:

        async def ids(**params: str | int) -> set[int]:
            response = await http.get("/simulations", params={**params, "limit": 1000})
            assert response.status_code == 200, response.text
            return {s["simulation_id"] for s in response.json()["simulations"]}

        ours = {recorded.linked, recorded.unlinked, recorded.legacy, recorded.private}
        assert await ids(simulator_id=recorded.earlier.database_id) == {recorded.legacy}
        assert await ids(simulator_id=recorded.versioned.database_id) == {recorded.linked, recorded.unlinked}
        assert (await ids(environment="viva-pde-particle")) & ours == {recorded.linked}
        label = f"viva-pde-particle@{recorded.number}"
        assert await ids(environment_version=label) == {recorded.linked}
        assert await ids(environment="viva-pde-particle", environment_version=label) == {recorded.linked}

        linked = (await http.get(f"/simulations/{recorded.linked}")).json()
        assert linked["environment_version"] == {"environment": "viva-pde-particle", "number": recorded.number}
        assert (await http.get(f"/simulations/{recorded.legacy}")).json()["environment_version"] is None

        for bad in (
            {"environment": "no-such-env"},
            {"environment_version": "registry_env"},
            {"environment_version": "viva-pde-particle@999999"},
            {"environment": "registry_env", "environment_version": label},
        ):
            assert (await http.get("/simulations", params=bad)).status_code == 400, bad
