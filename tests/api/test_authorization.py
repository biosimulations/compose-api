"""The read policy and the seam every simulation read goes through (docs/plan-observability.md O7, O8).

A private simulation is invisible, as not found, to anyone but its owner and admins: its status, its place in a batch
status and its results. The caller is the verified bearer-token principal (#192); these tests override get_caller to
choose one. No submission stamps an owner yet, so every real simulation is public and these tests create private ones
directly.
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


@pytest.mark.asyncio
async def test_a_comparison_of_a_private_simulation_is_not_found_except_by_its_owner(
    http: AsyncClient,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    """A comparison shows its runs' results, so it is readable only by someone who may read every run in it."""
    sim_db, cmp_db = database_service.get_simulator_db(), database_service.get_comparisons_db()
    private = await sim_db.insert_simulation(
        sim_request=simulation_request,
        experiment_id="experiment-authz-cmp-private",
        simulator_version=simulator,
        owner_sub=ALICE.subject,
        visibility=Visibility.PRIVATE,
    )
    public = await sim_db.insert_simulation(
        sim_request=simulation_request, experiment_id="experiment-authz-cmp-public", simulator_version=simulator
    )
    source = "upload:authz-comparison.omex"
    settings = {"reports": {"r": {"labels": ["t"]}}}
    mixed = await cmp_db.insert("mixed", source, "<sedml/>", "task", settings)
    await cmp_db.add_member(mixed, private.database_id, "copasi")
    await cmp_db.add_member(mixed, public.database_id, "tellurium")
    open_one = await cmp_db.insert("public", source, "<sedml/>", "task", settings)
    await cmp_db.add_member(open_one, public.database_id, "copasi")
    try:
        for caller in (None, BOB):
            _as(caller)
            assert (await http.get(f"/comparisons/{mixed}")).status_code == 404
            assert (await http.get(f"/comparisons/{mixed}/series", params={"report": "r"})).status_code == 404
            listed = (await http.get("/comparisons", params={"source": source})).json()
            assert [c["comparison_id"] for c in listed["comparisons"]] == [open_one]
            assert listed["total"] == 1
            assert (await http.get(f"/comparisons/{open_one}")).status_code == 200

        for caller in (ALICE, ADMIN):
            _as(caller)
            assert (await http.get(f"/comparisons/{mixed}")).status_code == 200
            listed = (await http.get("/comparisons", params={"source": source})).json()
            assert sorted(c["comparison_id"] for c in listed["comparisons"]) == sorted([mixed, open_one])
    finally:
        for sim in (private, public):  # members cascade; the comparisons stay, with no members
            await sim_db.delete_simulation(sim.database_id)
