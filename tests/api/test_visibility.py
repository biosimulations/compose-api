"""Visibility (docs/plan-favorites-and-studies.md, F3, step 1b): a signed-in submitter's runs are private unless they
ask for public, and the owner (or an admin) changes it later, a comparison's runs together."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from compose_api.api.main import app
from compose_api.authorization import Caller, get_caller, ownership_at_submit
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.models import Ownership, SimulationRequest, SimulatorVersion, Visibility
from tests.api.test_authorization import ALICE, BOB


def _as(caller: Caller | None) -> None:
    async def who() -> Caller | None:
        return caller

    app.dependency_overrides[get_caller] = who


@pytest_asyncio.fixture
async def http() -> AsyncGenerator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_caller, None)


@pytest_asyncio.fixture
async def runs(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion
) -> AsyncGenerator[dict[str, int]]:
    """Alice's private run alone; Alice's two runs compared; a comparison of Alice's run and Bob's; an anonymous run."""
    sim_db, comparisons = database_service.get_simulator_db(), database_service.get_comparisons_db()

    async def run(name: str, owner: str | None, visibility: Visibility = Visibility.PRIVATE) -> int:
        sim = await sim_db.insert_simulation(
            simulation_request, f"exp-vis-{name}", simulator, owner_sub=owner, visibility=visibility
        )
        return sim.database_id

    ids = {
        "alone": await run("alone", ALICE.subject),
        "a1": await run("a1", ALICE.subject),
        "a2": await run("a2", ALICE.subject),
        "mixed_alice": await run("mixed-alice", ALICE.subject, Visibility.PUBLIC),
        "mixed_bob": await run("mixed-bob", BOB.subject, Visibility.PUBLIC),
        "anonymous": await run("anonymous", None, Visibility.PUBLIC),
    }
    for members in (("a1", "a2"), ("mixed_alice", "mixed_bob")):
        comparison = await comparisons.insert(name="vis", source="upload:vis.omex", sedml="s", task="t", settings={})
        for key in members:
            await comparisons.add_member(comparison, ids[key], key)
    yield ids
    for sim_id in ids.values():
        await sim_db.delete_simulation(sim_id)


def test_a_signed_in_submitter_owns_a_private_run_unless_they_ask_for_public() -> None:
    assert ownership_at_submit(ALICE, None) == Ownership(owner_sub=ALICE.subject, visibility=Visibility.PRIVATE)
    assert ownership_at_submit(ALICE, Visibility.PUBLIC) == Ownership(
        owner_sub=ALICE.subject, visibility=Visibility.PUBLIC
    )
    assert ownership_at_submit(None, None) is None and ownership_at_submit(None, Visibility.PUBLIC) is None
    with pytest.raises(HTTPException) as refused:
        ownership_at_submit(None, Visibility.PRIVATE)
    assert refused.value.status_code == 400


async def _visibility(database_service: DatabaseServiceSQL, *ids: int) -> set[str]:
    found = await database_service.get_simulator_db().get_simulations_access(list(ids))
    return {a.visibility.value for a in found}


@pytest.mark.asyncio
async def test_the_owner_changes_a_runs_visibility(
    http: AsyncClient, runs: dict[str, int], database_service: DatabaseServiceSQL
) -> None:
    url = f"/simulations/{runs['alone']}"
    assert (await http.patch(url, json={"visibility": "public"})).status_code == 401
    _as(BOB)
    assert (await http.patch(url, json={"visibility": "public"})).status_code == 404  # private: not even seen
    assert (await http.get(url)).status_code == 404

    _as(ALICE)
    made_public = await http.patch(url, json={"visibility": "public"})
    assert made_public.json() == {"visibility": "public", "simulation_ids": [runs["alone"]]}
    _as(BOB)
    assert (await http.get(url)).json()["visibility"] == "public"  # now anyone reads it
    assert (await http.patch(url, json={"visibility": "private"})).status_code == 403  # but only Alice changes it
    _as(None)
    assert (await http.get(url)).status_code == 200

    _as(ALICE)
    assert (await http.patch(url, json={"visibility": "private"})).json()["visibility"] == "private"
    assert await _visibility(database_service, runs["alone"]) == {"private"}
    assert (await http.patch(url, json={"visibility": "secret"})).status_code == 422


@pytest.mark.asyncio
async def test_a_comparisons_runs_change_together(
    http: AsyncClient, runs: dict[str, int], database_service: DatabaseServiceSQL
) -> None:
    _as(ALICE)
    changed = (await http.patch(f"/simulations/{runs['a1']}", json={"visibility": "public"})).json()
    assert changed["simulation_ids"] == sorted([runs["a1"], runs["a2"]])
    assert await _visibility(database_service, runs["a1"], runs["a2"]) == {"public"}

    refused = await http.patch(f"/simulations/{runs['mixed_alice']}", json={"visibility": "private"})
    assert refused.status_code == 409 and str(runs["mixed_bob"]) in refused.json()["detail"]
    assert await _visibility(database_service, runs["mixed_alice"], runs["mixed_bob"]) == {"public"}  # neither


@pytest.mark.asyncio
async def test_a_run_with_no_owner_stays_public(http: AsyncClient, runs: dict[str, int]) -> None:
    _as(ALICE)
    refused = await http.patch(f"/simulations/{runs['anonymous']}", json={"visibility": "private"})
    assert refused.status_code == 403 and "no owner" in refused.json()["detail"]
