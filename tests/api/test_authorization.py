"""The read policy and the seam every simulation read goes through (docs/plan-observability.md O7, O8).

A private simulation is invisible, as not found, to anyone but its owner and admins: its status, its place in a batch
status and its results. Until auth lands every caller is anonymous and every simulation public, so nothing changes.
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from compose_api.api.main import app
from compose_api.authorization import ADMIN_ROLE, Caller, can_read, get_caller
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.models import JobType, SimulationAccess, SimulationRequest, SimulatorVersion, Visibility


@dataclass(frozen=True)
class FakeCaller:
    subject: str
    roles: frozenset[str] = field(default_factory=lambda: frozenset({"user"}))


ALICE, BOB = FakeCaller("auth0|alice"), FakeCaller("auth0|bob")
ADMIN = FakeCaller("auth0|root", frozenset({ADMIN_ROLE}))


def _access(visibility: Visibility, owner: str | None = "auth0|alice") -> SimulationAccess:
    return SimulationAccess(simulation_id=1, experiment_id="e", owner_sub=owner, visibility=visibility)


def test_public_is_readable_by_anyone() -> None:
    for caller in (None, ALICE, BOB, ADMIN):
        assert can_read(caller, _access(Visibility.PUBLIC))
        assert can_read(caller, _access(Visibility.PUBLIC, owner=None))


def test_private_is_readable_by_its_owner_and_admins_only() -> None:
    private = _access(Visibility.PRIVATE)
    assert can_read(ALICE, private) and can_read(ADMIN, private)
    assert not can_read(BOB, private) and not can_read(None, private)
    assert not can_read(ALICE, _access(Visibility.PRIVATE, owner=None))  # an unowned private simulation: admins only
    assert can_read(ADMIN, _access(Visibility.PRIVATE, owner=None))


def test_fake_caller_is_a_caller() -> None:
    caller: Caller = ALICE  # mypy checks the protocol; #192's AuthenticatedPrincipal has the same two attributes
    assert caller.subject == "auth0|alice"


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
async def test_a_private_simulation_is_not_found_except_by_its_owner(
    http: AsyncClient,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    sim_db, hpc_db = database_service.get_simulator_db(), database_service.get_hpc_db()
    private = await sim_db.insert_simulation(
        sim_request=simulation_request,
        experiment_id="experiment-authz-private",
        simulator_version=simulator,
        owner_sub=ALICE.subject,
        visibility=Visibility.PRIVATE,
    )
    public = await sim_db.insert_simulation(
        sim_request=simulation_request, experiment_id="experiment-authz-public", simulator_version=simulator
    )
    runs = [
        await hpc_db.insert_hpcrun(
            slurmjobid=7001 + i, job_type=JobType.SIMULATION, ref_id=s.database_id, correlation_id=f"corr-authz-{i}"
        )
        for i, s in enumerate((private, public))
    ]
    ids = [private.database_id, public.database_id]
    try:
        for caller in (None, BOB):
            _as(caller)
            r = await http.get("/results/simulation/status", params={"simulation_id": private.database_id})
            assert r.status_code == 404
            assert r.json()["detail"] == f"Simulation with id {private.database_id} not found."
            r = await http.get("/results/simulation/results/file", params={"simulation_id": private.database_id})
            assert r.status_code == 404
            batch = await http.request("GET", "/results/simulations/status/batch", json=ids)
            assert [run["sim_id"] for run in batch.json()] == [public.database_id]
            r = await http.get("/results/simulation/status", params={"simulation_id": public.database_id})
            assert r.status_code == 200

        for caller in (ALICE, ADMIN):
            _as(caller)
            r = await http.get("/results/simulation/status", params={"simulation_id": private.database_id})
            assert r.status_code == 200 and r.json()["trace_id"] == runs[0].trace_id
            batch = await http.request("GET", "/results/simulations/status/batch", json=ids)
            assert sorted(run["sim_id"] for run in batch.json()) == sorted(ids)
    finally:
        for run in runs:
            await hpc_db.delete_hpcrun(run.database_id)
        for sim in (private, public):
            await sim_db.delete_simulation(sim.database_id)


@pytest.mark.asyncio
async def test_a_new_run_has_its_trace_identity(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion
) -> None:
    from compose_api.observability.identity import trace_id_from_correlation

    sim = await database_service.get_simulator_db().insert_simulation(
        sim_request=simulation_request, experiment_id="experiment-authz-trace", simulator_version=simulator
    )
    run = await database_service.get_hpc_db().insert_hpcrun(
        slurmjobid=7101, job_type=JobType.SIMULATION, ref_id=sim.database_id, correlation_id="simulation-abc1234"
    )
    try:
        assert run.trace_id == trace_id_from_correlation("simulation-abc1234")
        access = await database_service.get_simulator_db().get_simulations_access([sim.database_id, 987_654_321])
        assert [(a.simulation_id, a.owner_sub, a.visibility) for a in access] == [
            (sim.database_id, None, Visibility.PUBLIC)
        ]
    finally:
        await database_service.get_hpc_db().delete_hpcrun(run.database_id)
        await database_service.get_simulator_db().delete_simulation(sim.database_id)
