"""A private repository's entry through the API (docs/plan-private-repo-usage.md, B). viva-basic-processes is made
private here, to a role of its own. Its holder gets a mash-up of it made and runs in it. To every other
caller (anonymous, signed in, or an administrator without the role) the entry, the mash-up, its versions, its simulator
and its runs do not exist: each answers exactly as something unknown does, and keeps doing so after the entry leaves
the manifest."""

import asyncio
import datetime
import importlib
import json
import re
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
import yaml
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import delete, select, update

from compose_api.api.main import APP_ROUTERS, app
from compose_api.authentication import DEFAULT_ROLE, AuthenticatedPrincipal, get_optional_principal
from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.db.tables.environment_tables import ORMEnvironment, ORMEnvironmentVersion
from compose_api.db.tables.hpc_tables import ORMHpcRun
from compose_api.db.tables.simulator_tables import ORMSimulation
from compose_api.environments import lifecycle, source_credentials
from compose_api.environments.source_credentials import PrivateSource
from compose_api.registry import manifest as manifest_module
from compose_api.registry.manifest import load_manifest
from compose_api.simulation import build_k8s
from compose_api.simulation.models import JobType, SimulationRequest, SimulatorVersion, Visibility
from tests.fixtures.mash_up_fixtures import Locks
from tests.fixtures.private_source_fixtures import TOKEN, FakeGitHub, RecordingBuilds, serialized

DOSE = "local:viva_basic_processes.intervention.Intervention"
MABOSS = "local:viva_maboss.processes.MaBoSSProcess"
UNREGISTERED = DOSE.replace("viva_basic_processes", "viva_nothing")
PRIVATE_MASH_UP = lifecycle.mash_up_name({"viva-basic-processes", "viva-maboss"})
PUBLIC_MASH_UP = lifecycle.mash_up_name({"viva-maboss"})
UNKNOWN = "mash-0000000000"
UNKNOWN_SIMULATOR = 999_999_999
ROLE = "repo-viva-basic-processes"  # a repository role, named as the plan names them (repo-<name>)


def _principal(subject: str, *roles: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject=subject, issuer="https://t/", audience=("a",), scopes=frozenset(), permissions=frozenset(),
        roles=frozenset({DEFAULT_ROLE, *roles}),
    )  # fmt: skip


HOLDER = _principal("auth0|holder", ROLE)
COLLEAGUE = _principal("auth0|colleague", ROLE)
OTHER = _principal("auth0|other")
ADMIN = _principal("auth0|admin", "admin")  # an administrator of everything, without the role
WITHOUT_THE_ROLE = (None, OTHER, ADMIN)

# Every route that names an environment or a simulator. To a caller without the role, each answers for the private
# mash-up exactly as for one that does not exist.
NAMED_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/registry/environments/{name}/manifest", None),
    ("GET", "/registry/environments/{name}/headers", None),
    ("GET", "/registry/environments/{name}/images", None),
    ("POST", "/registry/environments/{name}/build", None),
    ("GET", "/registry/environments/{name}/versions", None),
    ("POST", "/registry/environments/{name}/versions", {"note": "a new version"}),
    ("GET", "/registry/environments/{name}/versions/{number}", None),
    ("GET", "/registry/environments/{name}/versions/{number}/export", None),
    ("GET", "/registry/environments/{name}/versions/{number}/compliance", None),
    ("POST", "/registry/environments/{name}/versions/{number}/compliance", None),
    ("POST", "/registry/environments/{name}/versions/{number}/inspect", None),
    ("POST", "/registry/environments/{name}/versions/{number}/retire", None),
    ("PUT", "/registry/environments/{name}/default", {"number": 1}),
    ("GET", "/registry/simulators/{simulator_id}", None),
    ("GET", "/registry/simulators/{simulator_id}/images", None),
    ("POST", "/registry/simulators/{simulator_id}/build", None),
    ("GET", "/results/simulator/build/status?simulator_id={simulator_id}", None),
    ("GET", "/results/simulator/build/log?simulator_id={simulator_id}", None),
]
# Every route that lists environments, entries or simulators: each leaves the private ones out (``_assert_hidden``).
# Solvers are kept out of private environments by the CI rule (tests/registry/test_access.py).
LISTINGS = {
    ("GET", "/registry/environments"),
    ("GET", "/registry/entries"),
    ("GET", "/registry/simulators"),
    ("GET", "/core/simulator/list"),
    ("GET", "/registry/solvers"),
}
# Every other route that takes an environment or a simulator by name, and where that is checked.
NAMING = {
    ("POST", "/simulation/run"): "the submission tests below",
    ("GET", "/simulations"): "its filters answer 400 for a hidden name, as for an unknown one (_assert_hidden)",
    # `environment_version` names versions of the solvers' environments only, never a private one (the CI rule); any
    # other name is "not used by these runs", whether it exists or not (environments/versions.py, resolve_versions)
    ("POST", "/sedml/run"): "solver environments only",
    ("POST", "/sources/biomodels/{model_id}/run"): "solver environments only",
    ("POST", "/sources/biosimulations/{project_id}/run"): "solver environments only",
    ("POST", "/suites/{name}/run"): "solver environments only",
}
_LISTED_MODELS = ("EnvironmentSummary", "CatalogEntry", "SimulatorSummary", "RegisteredSimulators", "Solver")
_NAMING_PARAMETERS = {"environment", "environment_version", "simulator", "simulator_id"}


@pytest.fixture
def private_entry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_github: FakeGitHub) -> Callable[[], None]:
    """manifest.yaml as committed, with viva-basic-processes private to ``ROLE``; call the result to drop the entry from
    the manifest again, as a later release might. It installs from git, so its versions' Jobs fetch it with a token
    from this deployment's GitHub App (``fake_github``)."""
    committed = manifest_module._MANIFEST_PATH
    data = yaml.safe_load(committed.read_text())
    entry = next(e for e in data["entries"] if e["id"] == "viva-basic-processes")
    entry["access_role"] = ROLE
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(manifest_module, "_MANIFEST_PATH", path)
    assert next(e for e in load_manifest().entries if e.id == "viva-basic-processes").access_role == ROLE

    def dropped() -> None:
        data["entries"] = [e for e in data["entries"] if e["id"] != "viva-basic-processes"]
        path.write_text(yaml.safe_dump(data))
        # catalog.yaml's `listed` entry of that id stands in, without the role
        assert all(e.access_role is None for e in load_manifest().entries if e.id == "viva-basic-processes")

    return dropped


async def _remove(database_service: DatabaseServiceSQL, *names: str) -> None:
    """The mash-ups, their versions, and the runs in them."""
    async with database_service.async_sessionmaker() as session, session.begin():
        for name in names:
            env = (
                await session.execute(select(ORMEnvironment).where(ORMEnvironment.name == name))
            ).scalar_one_or_none()
            if env is None:
                continue
            versions = select(ORMEnvironmentVersion.id).where(ORMEnvironmentVersion.environment_id == env.id)
            runs = select(ORMSimulation.id).where(ORMSimulation.environment_version_id.in_(versions))
            for run in (await session.execute(runs)).scalars().all():
                await database_service.get_simulator_db().delete_simulation(run)
            simulators = select(ORMEnvironmentVersion.simulator_id).where(
                ORMEnvironmentVersion.environment_id == env.id
            )
            await session.execute(delete(ORMHpcRun).where(ORMHpcRun.simulator_id.in_(simulators)))
            await session.execute(
                update(ORMEnvironment).where(ORMEnvironment.id == env.id).values(default_version_id=None)
            )
            await session.execute(delete(ORMEnvironmentVersion).where(ORMEnvironmentVersion.environment_id == env.id))
            await session.execute(delete(ORMEnvironment).where(ORMEnvironment.id == env.id))


@pytest_asyncio.fixture
async def clean(database_service: DatabaseServiceSQL) -> AsyncIterator[None]:
    await _remove(database_service, PRIVATE_MASH_UP, PUBLIC_MASH_UP)
    yield
    await _remove(database_service, PRIVATE_MASH_UP, PUBLIC_MASH_UP)


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run is recorded and queued, as on the service; SLURM is never reached (no submission worker here)."""
    from compose_api.api.routers import simulation as simulation_router

    for service in ("get_simulation_service", "get_job_monitor"):
        monkeypatch.setattr(simulation_router, service, lambda: object())


@pytest.fixture
def as_caller() -> Iterator[Callable[[AuthenticatedPrincipal | None], FastAPI]]:
    def choose(principal: AuthenticatedPrincipal | None) -> FastAPI:
        app.dependency_overrides[get_optional_principal] = lambda: principal
        return app

    with override_settings(admin_role="admin", environment_admin_role="admin"):
        yield choose
    app.dependency_overrides.pop(get_optional_principal, None)


def _document(*addresses: str) -> tuple[str, bytes, str]:
    state = {f"p{i}": {"_type": "process", "address": a} for i, a in enumerate(addresses)}
    return ("doc.pbg", json.dumps({"state": state}).encode(), "application/json")


async def _submit(client: httpx.AsyncClient, *addresses: str, **params: str) -> httpx.Response:
    return await client.post("/simulation/run", files={"uploaded_file": _document(*addresses)}, params=params)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _answer(response: httpx.Response, *names: str) -> tuple[int, str]:
    """A response as a comparison of two names needs it: its status, and its text with each name blanked, and the
    upload's temporary file name, which differs on every request."""
    text = re.sub(r'"document":"[^"]*"', '"document":"?"', response.text)
    for name in names:
        text = text.replace(name, "?")
    return response.status_code, text


async def _holders_mash_up(as_caller: Any, database_service: DatabaseServiceSQL) -> tuple[int, int]:
    """The holder's run of the private class beside a public one: a mash-up made for it, its version recording the
    role and the run stamped with it. Its simulator gets a build record, so the build status route has one to show."""
    as_caller(HOLDER)
    async with _client() as client:
        made = await _submit(client, DOSE, MABOSS)
    assert made.status_code == 200, made.text
    version = await database_service.get_environments_db().get_default(PRIVATE_MASH_UP)
    assert version is not None and version.simulator_id is not None
    assert (version.spec or {})["access_roles"] == [ROLE]
    run = made.json()["simulation_database_id"]
    [access] = await database_service.get_simulator_db().get_simulations_access([run])
    assert access.access_roles == {ROLE} and access.owner_sub == HOLDER.subject
    await database_service.get_hpc_db().insert_hpcrun(
        slurmjobid=7301, job_type=JobType.BUILD_CONTAINER, ref_id=version.simulator_id, correlation_id="private-build"
    )
    return version.simulator_id, run


async def _assert_hidden(as_caller: Any, simulator_id: int, run: int, *, entry_private: bool = True) -> None:
    """To every caller without the role, the private mash-up, its simulator and the run are unknown, and so is the
    entry while it is private (gone from the manifest, catalog.yaml's public `listed` entry of that id stands in)."""
    for principal in WITHOUT_THE_ROLE:
        as_caller(principal)
        async with _client() as client:
            for method, path, body in NAMED_ROUTES:
                hidden = await client.request(
                    method, path.format(name=PRIVATE_MASH_UP, number=1, simulator_id=simulator_id), json=body
                )
                absent = await client.request(
                    method, path.format(name=UNKNOWN, number=1, simulator_id=UNKNOWN_SIMULATOR), json=body
                )
                assert _answer(hidden, PRIVATE_MASH_UP, str(simulator_id)) == _answer(
                    absent, UNKNOWN, str(UNKNOWN_SIMULATOR)
                ), (principal, method, path)
            assert PRIVATE_MASH_UP not in [e["name"] for e in (await client.get("/registry/environments")).json()]
            if entry_private:
                entries = [e["id"] for e in (await client.get("/registry/entries")).json()]
                assert "viva-basic-processes" not in entries
            assert simulator_id not in [s["simulator_id"] for s in (await client.get("/registry/simulators")).json()]
            listed = (await client.get("/core/simulator/list")).json()["versions"]
            assert simulator_id not in [v["database_id"] for v in listed]
            for flt in ({"environment": PRIVATE_MASH_UP}, {"environment_version": f"{PRIVATE_MASH_UP}@1"}):
                assert (await client.get("/simulations", params=flt)).status_code == 400
            assert (await client.get(f"/simulations/{run}")).status_code == 404
            assert run not in [s["simulation_id"] for s in (await client.get("/simulations")).json()["simulations"]]
            named = await _submit(client, MABOSS, environment=PRIVATE_MASH_UP, simulator="bogus")
            unknown = await _submit(client, MABOSS, environment=UNKNOWN, simulator="bogus")
            assert _answer(named, PRIVATE_MASH_UP) == _answer(unknown, UNKNOWN)
            named = await _submit(client, MABOSS, environment=PRIVATE_MASH_UP)
            unknown = await _submit(client, MABOSS, environment=UNKNOWN)
            assert _answer(named, PRIVATE_MASH_UP) == _answer(unknown, UNKNOWN)


@pytest.mark.asyncio
@pytest.mark.usefixtures("private_entry", "clean")
async def test_a_private_class_is_unregistered_to_a_caller_without_its_role(as_caller: Any, locks: Locks) -> None:
    for principal in WITHOUT_THE_ROLE:
        as_caller(principal)
        async with _client() as client:
            for params in ({}, {"environment": "registry_env"}):  # inferred, and named
                private = await _submit(client, DOSE, **params)
                unknown = await _submit(client, UNREGISTERED, **params)
                assert private.status_code == 400, private.text
                assert _answer(private, "viva_basic_processes") == _answer(unknown, "viva_nothing")
    assert locks.asked == []  # nothing was made of it


@pytest.mark.asyncio
@pytest.mark.usefixtures("private_entry", "clean", "queued")
async def test_its_holder_runs_it_and_to_everyone_else_none_of_it_exists(
    as_caller: Any, locks: Locks, builds: list[str], database_service: DatabaseServiceSQL
) -> None:
    simulator_id, run = await _holders_mash_up(as_caller, database_service)

    # another caller's run of a class it shares is never sent to the private mash-up: one is made for it alone
    as_caller(OTHER)
    async with _client() as client:
        theirs = await _submit(client, MABOSS)
    assert theirs.status_code == 200, theirs.text
    assert await database_service.get_environments_db().get_default(PUBLIC_MASH_UP) is not None

    await _assert_hidden(as_caller, simulator_id, run)

    as_caller(HOLDER)
    async with _client() as client:
        assert PRIVATE_MASH_UP in [e["name"] for e in (await client.get("/registry/environments")).json()]
        assert "viva-basic-processes" in [e["id"] for e in (await client.get("/registry/entries")).json()]
        assert (await client.get(f"/registry/environments/{PRIVATE_MASH_UP}/versions/1")).status_code == 200
        assert (await client.get(f"/registry/simulators/{simulator_id}")).status_code == 200
        status = await client.get("/results/simulator/build/status", params={"simulator_id": simulator_id})
        assert status.status_code == 200, status.text
        listing = await client.get("/simulations", params={"environment": PRIVATE_MASH_UP})
        assert run in [s["simulation_id"] for s in listing.json()["simulations"]]
        # made public by its owner: "public" is every holder of the role, never anyone else
        made_public = await client.patch(f"/simulations/{run}", json={"visibility": "public"})
        assert made_public.status_code == 200, made_public.text

    as_caller(COLLEAGUE)
    async with _client() as client:
        assert (await client.get(f"/simulations/{run}")).status_code == 200
    for principal in WITHOUT_THE_ROLE:
        as_caller(principal)
        async with _client() as client:
            assert (await client.get(f"/simulations/{run}")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.usefixtures("clean", "queued")
async def test_what_was_made_private_stays_hidden_after_the_entry_leaves_the_manifest(
    private_entry: Callable[[], None],
    as_caller: Any,
    locks: Locks,
    builds: list[str],
    database_service: DatabaseServiceSQL,
) -> None:
    """Its versions recorded the role when they were made, so a later manifest edit narrows nothing."""
    simulator_id, run = await _holders_mash_up(as_caller, database_service)
    private_entry()  # the entry leaves the manifest; the repository is still private
    await _assert_hidden(as_caller, simulator_id, run, entry_private=False)


@pytest.mark.asyncio
async def test_a_run_the_service_starts_for_a_private_entry_is_read_only_by_its_holders(
    as_caller: Any,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    """A compliance run has no owner and is public, so its roles are all that keep it from everyone else."""
    sim_db = database_service.get_simulator_db()
    case = await sim_db.insert_simulation(
        sim_request=simulation_request,
        experiment_id="experiment-private-compliance",
        simulator_version=simulator,
        visibility=Visibility.PUBLIC,
        access_roles=frozenset({ROLE}),
    )
    try:
        for principal, status in [(HOLDER, 200), (COLLEAGUE, 200), *((p, 404) for p in WITHOUT_THE_ROLE)]:
            as_caller(principal)
            async with _client() as client:
                assert (await client.get(f"/simulations/{case.database_id}")).status_code == status, principal
                listed = (await client.get("/simulations")).json()["simulations"]
                assert (case.database_id in [s["simulation_id"] for s in listed]) == (status == 200), principal
    finally:
        await sim_db.delete_simulation(case.database_id)


def test_every_route_that_names_or_lists_environments_or_simulators_is_checked() -> None:
    """The drift alarm: a new route that names or lists environments or simulators joins one of the tables above, so
    it is checked."""
    routes = [
        (config.prefix + route.path, route)
        for config in (importlib.import_module(f"compose_api.api.routers.{name}").config for name in APP_ROUTERS)
        for route in config.router.routes
        if isinstance(route, APIRoute)
    ]
    assert len(routes) > 50  # every router was walked
    named, listing, naming = set(), set(), set()
    for path, route in routes:
        query = {param.name for param in route.dependant.query_params}
        for method in route.methods or ():
            if path.startswith("/registry/environments/{name}") or "{simulator_id}" in path:
                named.add((method, path))
            elif any(model in str(route.response_model) for model in _LISTED_MODELS):
                listing.add((method, path))
            elif query & _NAMING_PARAMETERS:
                naming.add((method, path))
    checked = {(method, path.split("?")[0]) for method, path, _ in NAMED_ROUTES}
    assert named <= checked, sorted(named - checked)
    assert naming <= checked | set(NAMING), sorted(naming - checked - set(NAMING))
    assert listing == LISTINGS, sorted(listing ^ LISTINGS)
    assert checked <= named | naming and set(NAMING) <= naming  # no row names a route that is gone


def _basic_processes() -> PrivateSource:
    """The private repository, as the manifest installs it."""
    entry = next(e for e in load_manifest().entries if e.id == "viva-basic-processes")
    assert entry.install is not None and entry.install.git is not None and entry.install.commit is not None
    return PrivateSource(entry.install.git, entry.install.commit)


@pytest.mark.asyncio
@pytest.mark.usefixtures("private_entry", "clean", "queued")
async def test_without_a_token_nothing_is_made_and_the_next_run_makes_it(
    as_caller: Any, locks: Locks, builds: list[str], fake_github: FakeGitHub, database_service: DatabaseServiceSQL
) -> None:
    """GitHub gives no token: the run is a 503 and no version is recorded. A failed first version would refuse every
    later run of these classes with a 409 until an administrator stepped in; this one is simply tried again."""
    environments_db = database_service.get_environments_db()
    fake_github.available = False
    as_caller(HOLDER)
    async with _client() as client:
        refused = await _submit(client, DOSE, MABOSS)
    assert refused.status_code == 503, refused.text
    assert "private repositories cannot be read now" in refused.json()["detail"]
    assert locks.asked == [] and await environments_db.list_versions(PRIVATE_MASH_UP) == []

    fake_github.available = True
    await _holders_mash_up(as_caller, database_service)

    # an administrator holding the role asks for another version while GitHub is down: refused, nothing recorded
    source_credentials._tokens.clear()  # the run's token, which would still serve
    fake_github.available = False
    as_caller(_principal("auth0|operator", ROLE, "admin"))
    async with _client() as client:
        again = await client.post(f"/registry/environments/{PRIVATE_MASH_UP}/versions", json={"note": "again"})
    assert again.status_code == 503, again.text
    assert [v.number for v in await environments_db.list_versions(PRIVATE_MASH_UP)] == [1]


SITE = build_k8s.BuildSite(
    namespace="ns", image="ghcr.io/apptainer/apptainer:1.3.6", pvc_claim="home", pvc_mount_path="/projects/CRBM",
    pvc_sub_path="", run_as_uid=16997, run_as_gid=10000, supplemental_groups=(), timeout_seconds=600,
)  # fmt: skip


@pytest.mark.asyncio
@pytest.mark.usefixtures("private_entry", "clean", "queued")
async def test_its_jobs_alone_are_given_a_token_and_only_in_their_secrets(
    as_caller: Any,
    locks: Locks,
    builds: list[str],
    fake_github: FakeGitHub,
    database_service: DatabaseServiceSQL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The holder's mash-up and another caller's public one, each locked, built and given its uv form as the service
    would: the private one's Jobs read its repository with a token minted for it alone, the build's in its Secret; the
    public one's get none; and the token is in nothing the version records. (Its lock is pixi's, a stand-in here: the
    plan's local probes show pixi records the https URL and no token.)"""
    from compose_api.environments import service as environment_service
    from compose_api.environments import uv_export

    private = _basic_processes()
    fake_github.lifetime = datetime.timedelta(minutes=50)  # enough for a lock Job, not for a build
    await _holders_mash_up(as_caller, database_service)
    as_caller(OTHER)
    async with _client() as client:
        assert (await _submit(client, MABOSS)).status_code == 200
    assert locks.sources == [(private,), ()]
    assert fake_github.minted == [{"repositories": [private.repository[1]], "permissions": {"contents": "read"}}]

    monkeypatch.setattr(build_k8s.BuildSite, "from_settings", classmethod(lambda cls, s: SITE))
    monkeypatch.setattr(uv_export, "needs_conda", lambda spec: False)  # so each gets a uv form, whatever it installs
    uv_locked: list[tuple[PrivateSource, ...]] = []

    async def uv_lock(project: str, pixi_image: str, suffix: str, sources: Sequence[PrivateSource] = ()) -> str:
        uv_locked.append(tuple(sources))
        return "version = 1\n"

    monkeypatch.setattr(build_k8s, "uv_lock", uv_lock)
    environments_db = database_service.get_environments_db()
    for name, is_private in ((PRIVATE_MASH_UP, True), (PUBLIC_MASH_UP, False)):
        version = await environments_db.get_default(name)
        assert version is not None and version.simulator_id is not None
        detail = await environments_db.get_by_number(name, version.number)
        simulator = await database_service.get_simulator_db().get_simulator(version.simulator_id)
        assert detail is not None and simulator is not None
        recording = RecordingBuilds()
        monkeypatch.setattr(build_k8s, "k8s_builds", lambda r=recording: r)
        await build_k8s.submit_build(simulator, database_service.get_hpc_db(), "AbCdE")
        await environment_service.export_uv(database_service, version, "AbCdE")
        assert uv_locked[-1] == ((private,) if is_private else ())
        (job,) = recording.of("job")
        containers = job.spec.template.spec.init_containers
        recorded = json.dumps([detail.spec, simulator.container_def.representation])
        assert TOKEN not in recorded and TOKEN not in serialized(job)
        if not is_private:
            assert [c.name for c in containers] == ["build"] and recording.of("secret") == []
            continue
        assert [c.name for c in containers] == ["clone", "build"]
        assert f"fetch -q --depth 1 {private.url} {private.commit}\n" in containers[0].command[-1]
        (secret,) = recording.of("secret")
        assert secret.string_data["credentials"] == f"username=x-access-token\npassword={TOKEN}\n"
    # the run's token, with 50 minutes left, served the uv-lock Job; the build's clone was given a fresh one
    assert len(fake_github.minted) == 2


class _NoDownload:
    """A simulation service whose shared image repository has no image, so the image is built."""

    async def download_container(self, image: object) -> None:
        raise RuntimeError("not published")


@pytest.mark.asyncio
@pytest.mark.usefixtures("private_entry", "clean", "queued")
async def test_a_build_given_no_token_fails_its_version_and_says_why(
    as_caller: Any,
    locks: Locks,
    builds: list[str],
    fake_github: FakeGitHub,
    database_service: DatabaseServiceSQL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The build asks for a token of its own when it starts. If GitHub refuses then, nothing is built, and the version
    is failed with the reason, which the next run's 409 repeats instead of "see its page"."""
    from compose_api import dependencies

    fake_github.lifetime = datetime.timedelta(minutes=50)  # the run's token will not do for the build
    as_caller(HOLDER)
    async with _client() as client:
        assert (await _submit(client, DOSE, MABOSS)).status_code == 200
    environments_db = database_service.get_environments_db()
    version = await environments_db.get_default(PRIVATE_MASH_UP)
    assert version is not None and version.simulator_id is not None
    simulator = await database_service.get_simulator_db().get_simulator(version.simulator_id)
    assert simulator is not None

    fake_github.available = False
    recording = RecordingBuilds()
    monkeypatch.setattr(build_k8s, "k8s_builds", lambda: recording)
    monkeypatch.setattr(build_k8s.BuildSite, "from_settings", classmethod(lambda cls, s: SITE))
    monkeypatch.setattr(dependencies, "get_required_simulation_service", lambda: _NoDownload())
    monkeypatch.setattr(dependencies, "get_required_job_monitor", lambda: object())
    with override_settings(build_backend="k8s"):  # a build that started would wait on a monitor there is none of
        await asyncio.wait_for(lifecycle.build_version(version, simulator), timeout=30)
    assert recording.calls == []  # no Job: the token is had before anything is created
    failed = await environments_db.get_version(version.database_id)
    assert failed is not None and failed.state == "failed"
    assert (failed.failure or "").startswith("its build could not read its repositories: GitHub gave no read access")
    async with _client() as client:
        again = await _submit(client, DOSE, MABOSS)
    assert again.status_code == 409 and "could not read its repositories" in again.json()["detail"]
