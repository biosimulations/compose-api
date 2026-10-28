"""``GET /simulations`` and ``GET /simulations/{id}``: finding simulations, with the read policy applied."""

import datetime
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from compose_api.api.main import app
from compose_api.authorization import get_caller
from compose_api.common.hpc.models import SlurmJob
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.observability.datasets import ORIGIN_MANIFEST, ArtifactRecord
from compose_api.observability.events import RunEvent
from compose_api.simulation.containerization import ContainerizationEngine
from compose_api.simulation.hpc_utils import get_singularity_hash
from compose_api.simulation.models import JobType, SimulationRequest, SubmissionSpec, Visibility
from compose_api.simulation.prebuilt import prebuilt_definition
from tests.api.test_authorization import ALICE
from tests.fixtures.postgres_fixtures import register_prebuilt

IMAGE = "ghcr.io/example/sim@sha256:" + "0" * 64


@pytest_asyncio.fixture
async def simulations(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[dict[str, int]]:
    await register_prebuilt(database_service, "viva-pde-particle", IMAGE)  # its versions name its runs (D8.3)
    sim_db, hpc_db = database_service.get_simulator_db(), database_service.get_hpc_db()
    definition = prebuilt_definition(IMAGE)
    simulator = await sim_db.get_simulator_by_def_hash(get_singularity_hash(definition))
    simulator = simulator or await sim_db.insert_simulator(definition, packages_used=None)
    assert simulator.container_def.containerization_engine == ContainerizationEngine.APPTAINER

    async def simulation(
        name: str,
        owner: str | None = None,
        visibility: Visibility = Visibility.PUBLIC,
        labelled: dict[str, object] | None = None,
    ) -> int:
        sim = await sim_db.insert_simulation(
            sim_request=simulation_request.model_copy(update=labelled or {}),
            experiment_id=f"exp-list-{name}",
            simulator_version=simulator,
            owner_sub=owner,
            visibility=visibility,
        )
        return sim.database_id

    ids = {
        "submitting": await simulation("submitting"),
        "completed": await simulation(
            "completed",
            labelled={
                "labels": {"source": "biomodels", "model": "BIOMD0000000012", "solver": "copasi"},
                "tags": ["repressilator", "demo"],
                "description": "Elowitz 2000 on COPASI",
            },
        ),
        "private": await simulation("private", ALICE.subject, Visibility.PRIVATE),
    }
    run = await hpc_db.insert_hpcrun(
        slurmjobid=9301, job_type=JobType.SIMULATION, ref_id=ids["completed"], correlation_id="simulation-list01"
    )
    await hpc_db.update_hpcrun_status(
        run.database_id, SlurmJob(job_id=9301, name="x", account="a", user_name="u", job_state="COMPLETED")
    )
    await database_service.get_events_db().insert_events(
        run.database_id,
        run.trace_id or "",
        [RunEvent(seq=i, source="job-9301", ts="2026-10-07T12:00:00Z", component="c", event="e") for i in (1, 2, 3)],
    )
    await database_service.get_datasets_db().register(
        ids["completed"], run.database_id, [ArtifactRecord(path="output/a.csv", origin=ORIGIN_MANIFEST)]
    )
    ids["run"] = run.database_id
    yield ids
    app.dependency_overrides.pop(get_caller, None)
    await hpc_db.delete_hpcrun(run.database_id)
    for key in ("submitting", "completed", "private"):
        await sim_db.delete_simulation(ids[key])
    await sim_db.delete_simulator(simulator.database_id)


@pytest.mark.asyncio
async def test_list_newest_first_with_status_and_filters(simulations: dict[str, int]) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        page = (await http.get("/simulations")).json()
        listed = [s["simulation_id"] for s in page["simulations"]]
        assert listed == [simulations["completed"], simulations["submitting"]]  # the private one is not listed
        assert page["total"] == 2
        done = page["simulations"][0]
        assert done["status"] == "completed" and done["slurm_job_id"] == 9301 and done["trace_id"]
        assert done["simulator"] == "viva-pde-particle"
        assert page["simulations"][1]["status"] == "submitting" and page["simulations"][1]["slurm_job_id"] is None

        only = (await http.get("/simulations", params={"status": "submitting"})).json()
        assert [s["simulation_id"] for s in only["simulations"]] == [simulations["submitting"]]
        by_name = (await http.get("/simulations", params={"simulator": "viva-pde-particle", "limit": 1})).json()
        assert by_name["total"] == 2 and by_name["next_offset"] == 1
        later = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(hours=1)
        assert (await http.get("/simulations", params={"since": later.isoformat()})).json()["total"] == 0
        assert (await http.get("/simulations", params={"status": "bogus"})).status_code == 422

        detail = (await http.get(f"/simulations/{simulations['completed']}")).json()
        assert (detail["event_count"], detail["dataset_count"], detail["status"]) == (3, 1, "completed")
        assert (await http.get(f"/simulations/{simulations['private']}")).status_code == 404
        assert (await http.get("/simulations/987654321")).status_code == 404


@pytest.mark.asyncio
async def test_the_owner_sees_their_private_simulation(simulations: dict[str, int]) -> None:
    async def alice() -> object:
        return ALICE

    app.dependency_overrides[get_caller] = alice
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        listed = {s["simulation_id"] for s in (await http.get("/simulations")).json()["simulations"]}
        assert simulations["private"] in listed
        detail = (await http.get(f"/simulations/{simulations['private']}")).json()
        assert detail["visibility"] == "private" and detail["status"] == "submitting"


@pytest.mark.asyncio
async def test_labels_and_tags_are_listed_and_filter(simulations: dict[str, int]) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        detail = (await http.get(f"/simulations/{simulations['completed']}")).json()
        assert detail["labels"] == {"source": "biomodels", "model": "BIOMD0000000012", "solver": "copasi"}
        assert detail["tags"] == ["repressilator", "demo"] and detail["description"] == "Elowitz 2000 on COPASI"
        plain = (await http.get(f"/simulations/{simulations['submitting']}")).json()
        assert (plain["labels"], plain["tags"], plain["description"]) == ({}, [], None)

        async def ids(**params: str | list[str]) -> list[int]:
            page = (await http.get("/simulations", params=params)).json()
            return [s["simulation_id"] for s in page["simulations"]]

        assert await ids(label="model:BIOMD0000000012") == [simulations["completed"]]
        assert await ids(label=["source:biomodels", "solver:copasi"]) == [simulations["completed"]]
        assert await ids(label=["source:biomodels", "solver:tellurium"]) == []
        assert await ids(tag="demo") == [simulations["completed"]]
        assert await ids(tag=["demo", "repressilator"]) == [simulations["completed"]]
        assert await ids(tag=["demo", "other"]) == []
        assert (await http.get("/simulations", params={"label": "colour:red"})).status_code == 400
        assert (await http.get("/simulations", params={"label": "model"})).status_code == 400


@pytest.mark.asyncio
async def test_a_queued_run_shows_its_submission_and_place_in_line(
    database_service: DatabaseServiceSQL, simulation_request: SimulationRequest, simulations: dict[str, int]
) -> None:
    """docs/plan-durable-submission.md, step 4: `status` stays `submitting`; `submission` says where the run is."""
    sim_db = database_service.get_simulator_db()
    simulator = await sim_db.get_simulator_by_def_hash(get_singularity_hash(prebuilt_definition(IMAGE)))
    assert simulator is not None

    async def queued(name: str, **placement: object) -> int:
        spec = SubmissionSpec(staged_on_store=False, **placement)  # type: ignore[arg-type]
        sim = await sim_db.insert_simulation(simulation_request, f"exp-queued-{name}", simulator, submission=spec)
        return sim.database_id

    first = await queued("first")
    second = await queued("second")
    suite = await queued("suite", queue="suite:x", priority=-10)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            detail = (await http.get(f"/simulations/{second}")).json()
            assert detail["status"] == "submitting"
            assert detail["submission"] == {
                "state": "requested", "queue": "interactive", "position": 2, "attempts": 0, "last_error": None,
            }  # fmt: skip
            assert (await http.get(f"/simulations/{first}")).json()["submission"]["position"] == 1
            assert (await http.get(f"/simulations/{suite}")).json()["submission"]["position"] == 3  # behind both
            # recorded before the queue: no submission
            assert (await http.get(f"/simulations/{simulations['completed']}")).json()["submission"] is None
    finally:
        for simulation_id in (first, second, suite):
            await sim_db.delete_simulation(simulation_id)  # the fixture removes the simulator


@pytest.mark.asyncio
async def test_mine_lists_the_callers_own_runs_and_needs_sign_in(
    simulations: dict[str, int], database_service: DatabaseServiceSQL, simulation_request: SimulationRequest
) -> None:
    """docs/plan-favorites-and-studies.md, step 1a: `mine` filters by owner, each run says whether it is the caller's,
    and no owner is named."""
    sim_db = database_service.get_simulator_db()
    template = await sim_db.get_simulation_row(simulations["completed"])
    assert template is not None
    simulator = await sim_db.get_simulator(template.simulation.simulator_id)
    assert simulator is not None
    owned = await sim_db.insert_simulation(simulation_request, "exp-list-owned", simulator, owner_sub=ALICE.subject)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            anonymous = await http.get("/simulations", params={"mine": True})
            assert anonymous.status_code == 401 and anonymous.headers["www-authenticate"] == "Bearer"
            everyone = (await http.get("/simulations")).json()["simulations"]
            assert not any(s["mine"] for s in everyone) and all("owner_sub" not in s for s in everyone)

            async def alice() -> object:
                return ALICE

            app.dependency_overrides[get_caller] = alice
            mine = (await http.get("/simulations", params={"mine": True})).json()
            assert {s["simulation_id"] for s in mine["simulations"]} == {owned.database_id, simulations["private"]}
            assert all(s["mine"] for s in mine["simulations"]) and mine["total"] == 2
            listed = {s["simulation_id"]: s["mine"] for s in (await http.get("/simulations")).json()["simulations"]}
            assert listed[owned.database_id] and not listed[simulations["completed"]]
            assert (await http.get(f"/simulations/{owned.database_id}")).json()["mine"] is True
    finally:
        await sim_db.delete_simulation(owned.database_id)
