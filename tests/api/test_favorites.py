"""Favorites (docs/plan-favorites-and-studies.md, F5, step 2): a signed-in user's private stars on simulations,
comparisons and suite runs, and the `favorite` filter and flag on the simulations and comparisons lists."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from compose_api.api.main import app
from compose_api.authorization import Caller, get_caller
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.favorites import FavoriteKind, FavoriteRefError, normalize_ref
from compose_api.simulation.models import SimulationRequest, SimulatorVersion, Visibility
from tests.api.test_authorization import ALICE, BOB

SOURCE = "upload:favorites-test.omex"


@pytest_asyncio.fixture
async def http() -> AsyncGenerator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_caller, None)


def _as(caller: Caller | None) -> None:
    async def who() -> Caller | None:
        return caller

    app.dependency_overrides[get_caller] = who


@pytest_asyncio.fixture
async def things(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulator: SimulatorVersion
) -> AsyncGenerator[dict[str, int]]:
    """A public simulation, Alice's private one, a comparison of the public one, and Alice's private one's."""
    sim_db, comparisons = database_service.get_simulator_db(), database_service.get_comparisons_db()
    public = await sim_db.insert_simulation(simulation_request, "exp-fav-public", simulator)
    private = await sim_db.insert_simulation(
        simulation_request, "exp-fav-private", simulator, owner_sub=ALICE.subject, visibility=Visibility.PRIVATE
    )
    ids = {"public": public.database_id, "private": private.database_id}
    for key, member in (("comparison", ids["public"]), ("private_comparison", ids["private"])):
        ids[key] = await comparisons.insert(name=f"fav {key}", source=SOURCE, sedml="s.sedml", task="t", settings={})
        await comparisons.add_member(ids[key], member, "copasi")
    yield ids
    for key in ("public", "private"):
        await sim_db.delete_simulation(ids[key])


def test_references_are_normalized() -> None:
    assert normalize_ref(FavoriteKind.SIMULATION, " 0012 ") == "12"
    assert normalize_ref(FavoriteKind.SUITE_RUN, "smoke@022") == "smoke@22"
    for kind, bad in (
        (FavoriteKind.SIMULATION, "x"),
        (FavoriteKind.SUITE_RUN, "smoke"),
        (FavoriteKind.SUITE_RUN, "@3"),
    ):
        with pytest.raises(FavoriteRefError):
            normalize_ref(kind, bad)


@pytest.mark.asyncio
async def test_favorites_need_sign_in(http: AsyncClient) -> None:
    for method, url in (
        ("PUT", "/favorites/simulation/1"),
        ("DELETE", "/favorites/simulation/1"),
        ("GET", "/favorites"),
    ):
        response = await http.request(method, url)
        assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer", url
    assert (await http.get("/simulations", params={"favorite": True})).status_code == 401
    assert (await http.get("/comparisons", params={"favorite": True})).status_code == 401


@pytest.mark.asyncio
async def test_a_star_is_the_users_own_and_filters_the_lists(http: AsyncClient, things: dict[str, int]) -> None:
    _as(BOB)
    starred = await http.put(f"/favorites/simulation/{things['public']:04d}")
    assert starred.status_code == 200 and starred.json()["ref"] == str(things["public"])
    again = await http.put(f"/favorites/simulation/{things['public']}")  # idempotent
    assert again.json()["created_at"] == starred.json()["created_at"]
    assert (await http.put(f"/favorites/comparison/{things['comparison']}")).status_code == 200

    listed = (await http.get("/favorites")).json()
    assert [(f["kind"], f["ref"]) for f in listed] == [
        ("comparison", str(things["comparison"])),
        ("simulation", str(things["public"])),
    ]
    assert [f["kind"] for f in (await http.get("/favorites", params={"kind": "comparison"})).json()] == ["comparison"]

    page = (await http.get("/simulations", params={"favorite": True})).json()
    assert [s["simulation_id"] for s in page["simulations"]] == [things["public"]] and page["simulations"][0][
        "favorite"
    ]
    assert (await http.get(f"/simulations/{things['public']}")).json()["favorite"] is True
    comparisons = (await http.get("/comparisons", params={"favorite": True})).json()["comparisons"]
    assert [c["comparison_id"] for c in comparisons] == [things["comparison"]] and comparisons[0]["favorite"]
    assert (await http.get(f"/comparisons/{things['comparison']}")).json()["favorite"] is True

    _as(ALICE)  # Bob's stars are his alone
    assert (await http.get("/favorites")).json() == []
    assert (await http.get(f"/simulations/{things['public']}")).json()["favorite"] is False
    assert (await http.get("/simulations", params={"favorite": True})).json()["total"] == 0

    _as(BOB)
    removed = await http.delete(f"/favorites/simulation/{things['public']}")
    assert removed.json() == {"kind": "simulation", "ref": str(things["public"]), "removed": True}
    assert (await http.delete(f"/favorites/simulation/{things['public']}")).json()["removed"] is False
    assert [f["kind"] for f in (await http.get("/favorites")).json()] == ["comparison"]
    await http.delete(f"/favorites/comparison/{things['comparison']}")


@pytest.mark.asyncio
async def test_starring_needs_read_access(http: AsyncClient, things: dict[str, int]) -> None:
    _as(BOB)
    for kind, key in (("simulation", "private"), ("comparison", "private_comparison")):
        assert (await http.put(f"/favorites/{kind}/{things[key]}")).status_code == 404
    assert (await http.put("/favorites/simulation/999999999")).status_code == 404
    assert (await http.put("/favorites/suite_run/smoke@999999")).status_code == 404
    assert (await http.put("/favorites/suite_run/no-such-suite@1")).status_code == 404
    assert (await http.put("/favorites/simulation/abc")).status_code == 400
    assert (await http.put("/favorites/suite_run/smoke")).status_code == 400
    assert (await http.put("/favorites/project/1")).status_code == 422

    _as(ALICE)  # the owner may
    assert (await http.put(f"/favorites/simulation/{things['private']}")).status_code == 200
    assert (await http.put(f"/favorites/comparison/{things['private_comparison']}")).status_code == 200
    assert len((await http.get("/favorites")).json()) == 2
    await http.delete(f"/favorites/simulation/{things['private']}")
    await http.delete(f"/favorites/comparison/{things['private_comparison']}")


@pytest.mark.asyncio
async def test_a_suite_run_is_starred_by_suite_and_number(
    http: AsyncClient, database_service: DatabaseServiceSQL
) -> None:
    _, number = await database_service.get_comparisons_db().new_suite_run("smoke", [])
    _as(ALICE)
    starred = await http.put(f"/favorites/suite_run/smoke@{number}")
    assert starred.status_code == 200 and starred.json()["ref"] == f"smoke@{number}"
    assert [f["ref"] for f in (await http.get("/favorites", params={"kind": "suite_run"})).json()] == [
        f"smoke@{number}"
    ]
    await http.delete(f"/favorites/suite_run/smoke@{number}")


@pytest.mark.asyncio
async def test_a_star_on_what_became_unreadable_is_kept_but_not_listed(
    http: AsyncClient, things: dict[str, int], database_service: DatabaseServiceSQL
) -> None:
    """F5: a star is not removed when what it marks stops being readable (or is deleted); it is only not listed."""
    await database_service.get_favorites_db().add(BOB.subject, FavoriteKind.SIMULATION, str(things["private"]))
    _as(BOB)
    assert (await http.get("/favorites")).json() == []
    assert (await http.get("/simulations", params={"favorite": True})).json()["total"] == 0
    assert await database_service.get_favorites_db().refs(BOB.subject, FavoriteKind.SIMULATION) == {
        str(things["private"])
    }
    await database_service.get_favorites_db().remove(BOB.subject, FavoriteKind.SIMULATION, str(things["private"]))
