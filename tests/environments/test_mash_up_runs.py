"""Runs in a composed environment the deployment does not declare (docs/plan-environment-composition.md, step 7b-2):
a mash-up the database holds is named with `environment=`, its version is chosen, its members admit the run, and its
compliance cases run in it. Step 7b-3 creates mash-ups from a run; here one is made directly, ready, as a build would
leave it."""

import json
import uuid
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.db.services.environments_db import VersionSource
from compose_api.db.tables.environment_tables import ORMEnvironment
from compose_api.environments import pixi
from compose_api.environments.versions import VersionUnavailableError, version_for
from compose_api.simulation import handlers
from compose_api.simulation.containerization import ContainerizationEngine, ContainerizationFileRepr
from compose_api.simulation.job_monitor import JobMonitor
from compose_api.simulation.models import Ownership, SimulationFileType, SimulationRequest, VersionState, Visibility
from compose_api.simulation.simulation_service import SimulationService
from tests.fixtures.mocks import TestBackgroundTask

ENTRIES = ["libvcell", "pbsim-common", "python-copasi", "pyvcell", "tellurium", "viva-basic-processes"]
COPASI = "local:pbsim_common.simulators.copasi_process.CopasiUTCStep"
DOSE = "local:viva_basic_processes.intervention.Intervention"
ACTIN = "local:pb_multiscale_actin.processes.Actin"  # an entry registry_env has and this mash-up does not


async def _ready_mash_up(database_service: DatabaseServiceSQL) -> tuple[str, int]:
    """A mash-up with one ready composed version, its default: (name, version id)."""
    name = f"mash-{uuid.uuid4().hex[:10]}"
    async with database_service.async_sessionmaker() as session, session.begin():
        session.add(ORMEnvironment(name=name, kind="mash-up", entries=ENTRIES))
    version_id = await _ready_version(database_service, name)
    await database_service.get_environments_db().set_default(name, version_id)
    return name, version_id


async def _ready_version(database_service: DatabaseServiceSQL, name: str) -> int:
    """A new ready composed version of the mash-up, as a build would leave it: its id."""
    environments_db = database_service.get_environments_db()
    spec = {"entries": [{"id": e} for e in ENTRIES]}
    source = VersionSource(spec=spec, origin="registry", runtime_contract=pixi.RUNTIME_CONTRACT)
    version = await environments_db.create_resolving(name, "mash-up", source)
    definition = ContainerizationFileRepr(
        representation=f"Bootstrap: docker\nFrom: example/{name}:{version.database_id}\n",
        containerization_engine=ContainerizationEngine.APPTAINER,
    )
    simulator = await database_service.get_simulator_db().insert_simulator(definition)
    await environments_db.set_resolved(version.database_id, simulator.database_id, "lock", uuid.uuid4().hex * 2)
    await environments_db.set_state(version.database_id, VersionState.READY)
    return version.database_id


def _document(tmp_path: Path, *addresses: str) -> Path:
    path = tmp_path / "doc.pbg"
    state = {f"p{i}": {"_type": "process", "address": a} for i, a in enumerate(addresses)}
    path.write_text(json.dumps({"state": state}))
    return path


@pytest.mark.asyncio
async def test_a_run_naming_a_mash_up_runs_in_its_default_version(
    database_service: DatabaseServiceSQL, tmp_path: Path
) -> None:
    name, version_id = await _ready_mash_up(database_service)
    version, _ = await version_for(database_service, None, None, name)
    assert version.database_id == version_id
    request = SimulationRequest(
        request_file_path=_document(tmp_path, COPASI, DOSE),
        simulation_file_type=SimulationFileType.PBG,
        environment=name,
        is_batch=False,
    )
    experiment = await handlers.run_simulation(
        simulation_request=request,
        database_service=database_service,
        simulation_service_slurm=cast(SimulationService, None),  # the queued submission is never taken here
        job_monitor=cast(JobMonitor, None),
        background_tasks=TestBackgroundTask(),
    )
    row = await database_service.get_simulator_db().get_simulation_row(experiment.simulation_database_id)
    assert row is not None and row.simulation.environment_version_id == version_id
    assert row.simulation.owner_sub is None  # nobody signed in (docs/plan-favorites-and-studies.md, F1)
    owned = await handlers.run_simulation(
        simulation_request=request,
        database_service=database_service,
        simulation_service_slurm=cast(SimulationService, None),
        job_monitor=cast(JobMonitor, None),
        background_tasks=TestBackgroundTask(),
        ownership=Ownership(owner_sub="auth0|submitter"),
    )
    owned_row = await database_service.get_simulator_db().get_simulation_row(owned.simulation_database_id)
    assert owned_row is not None and owned_row.simulation.owner_sub == "auth0|submitter"  # on the simulation only
    assert owned_row.simulation.visibility == Visibility.PRIVATE  # private by default (F3)
    assert row.simulation.labels["environment_version"] == f"{name}@1"
    with pytest.raises(VersionUnavailableError, match="no default"):
        await version_for(database_service, None, None, "mash-0000000000")  # unknown: nothing to adopt


@pytest.mark.asyncio
async def test_a_mash_up_admits_its_own_entries_and_refuses_others(
    http_api_client: httpx.AsyncClient, database_service: DatabaseServiceSQL, tmp_path: Path
) -> None:
    name, _ = await _ready_mash_up(database_service)

    async def submit(*addresses: str, **params: Any) -> httpx.Response:
        files = {"uploaded_file": ("doc.pbg", _document(tmp_path, *addresses).read_bytes(), "application/json")}
        return await http_api_client.post("/simulation/run", params={"environment": name, **params}, files=files)

    admitted = await submit(COPASI, DOSE)
    assert not (admitted.status_code == 400 and "violations" in admitted.text), admitted.text
    refused = await submit(COPASI, ACTIN)
    assert refused.status_code == 400
    (violation,) = refused.json()["detail"]["violations"]
    assert violation["address"] == ACTIN and f"not part of {name}@1" in violation["reason"]
    assert (await submit(COPASI, simulator="viva-pde-particle")).status_code == 400  # a mash-up is not an image
    unknown = await http_api_client.post(
        "/simulation/run",
        params={"environment": "mash-ffffffffff"},
        files={"uploaded_file": ("doc.pbg", _document(tmp_path, COPASI).read_bytes(), "application/json")},
    )
    assert unknown.status_code == 400 and "No environment" in unknown.json()["detail"]


@pytest.mark.asyncio
async def test_a_mash_ups_compliance_cases_run_in_the_mash_up(
    database_service: DatabaseServiceSQL, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each member entry's cases run in the version that has them, so the mash-up's own, never registry_env's."""
    from compose_api import dependencies
    from compose_api.environments import compliance_runs

    name, version_id = await _ready_mash_up(database_service)
    version = await database_service.get_environments_db().get_version(version_id)
    assert version is not None
    sent: list[SimulationRequest] = []
    run_simulation = handlers.run_simulation

    async def record(simulation_request: SimulationRequest, **kwargs: Any) -> Any:
        sent.append(simulation_request)
        return await run_simulation(simulation_request=simulation_request, **kwargs)

    for service in ("get_required_simulation_service", "get_required_job_monitor"):
        monkeypatch.setattr(dependencies, service, lambda: None)
    monkeypatch.setattr(handlers, "run_simulation", record)
    submitted = await compliance_runs.start(database_service, version)
    assert submitted == len(sent) and submitted >= 3  # pbsim-common's two cases and viva-basic-processes' one
    assert {r.environment for r in sent} == {name}
    assert "viva-basic-processes/intervention-and-expression" in {r.labels["compliance"] for r in sent}


@pytest.mark.asyncio
async def test_an_administrator_chooses_a_mash_ups_default_and_retires_its_versions(
    database_service: DatabaseServiceSQL,
) -> None:
    """A mash-up's later versions are an administrator's (`environments create`), and so are its default and its
    retirements: the routes find it in the database, as the reading ones do (7c-5 found `PUT …/default` a 404)."""
    from fastapi import FastAPI
    from httpx import ASGITransport

    from compose_api.api.routers import registry as registry_router
    from compose_api.authorization import get_caller
    from compose_api.config import override_settings
    from tests.environments.test_version_routes import ADMIN, ROLE

    name, first = await _ready_mash_up(database_service)
    second = await _ready_version(database_service, name)
    app = FastAPI()
    app.include_router(registry_router.config.router, prefix=registry_router.config.prefix)
    app.dependency_overrides[get_caller] = lambda: ADMIN
    url = f"/registry/environments/{name}"
    with override_settings(environment_admin_role=ROLE):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as admin:
            made = await admin.put(f"{url}/default", json={"number": 2})
            assert made.status_code == 200, made.text
            listed = (await admin.get(f"{url}/versions")).json()
            assert (listed["default"], listed["default_source"]) == (2, "api")
            assert (await admin.post(f"{url}/versions/2/retire")).status_code == 409  # the default
            retired = await admin.post(f"{url}/versions/1/retire")
            assert retired.status_code == 200 and retired.json()["state"] == "retired"
            unknown = await admin.put("/registry/environments/mash-ffffffffff/default", json={"number": 1})
            assert unknown.status_code == 404
    version, _ = await version_for(database_service, None, None, name)
    assert version.database_id == second != first
