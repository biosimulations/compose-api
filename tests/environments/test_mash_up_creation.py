"""Mash-ups made for a run (docs/plan-environment-composition.md, step 7b-3; D7.3 to D7.7): a run whose classes no
environment covers gets the mash-up of exactly their entries, locked while the request waits, built in the background,
used again by the next run that needs the same set; only a signed-in caller causes one, two at a time."""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import BackgroundTasks, FastAPI
from sqlalchemy import select

from compose_api.api.main import app as api_app
from compose_api.authentication import DEFAULT_ROLE, AuthenticatedPrincipal, get_optional_principal
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.environments import lifecycle
from compose_api.registry.environments import EnvironmentSpec, load_environments
from compose_api.registry.manifest import load_manifest
from compose_api.registry.resolver import covering_environment, needed_entries
from compose_api.simulation.models import SimulationFileType, SimulatorVersion, VersionState

COPASI = "local:pbsim_common.simulators.copasi_process.CopasiUTCStep"
DOSE = "local:viva_basic_processes.intervention.Intervention"
NEEDED = {"libvcell", "pbsim-common", "python-copasi", "pyvcell", "tellurium", "viva-basic-processes"}
USER = AuthenticatedPrincipal(
    subject="auth0|someone", issuer="https://t/", audience=("a",), scopes=frozenset(), permissions=frozenset(),
    roles=frozenset({DEFAULT_ROLE}),
)  # fmt: skip


@dataclass
class Locks:
    """The lock Job, replaced: a distinct lock per request, or a refusal."""

    refuse: str | None = None
    asked: list[str] = field(default_factory=list)

    async def __call__(self, toml: str, pixi_image: str, suffix: str) -> str:
        from compose_api.simulation.build_k8s import LockFailedError

        self.asked.append(toml)
        if self.refuse is not None:
            raise LockFailedError(self.refuse)
        return f"version: 7\n# {uuid.uuid4().hex}\n"


@pytest.fixture
def locks(monkeypatch: pytest.MonkeyPatch) -> Locks:
    from compose_api.simulation import build_k8s

    fake = Locks()
    monkeypatch.setattr(build_k8s, "lock_composed", fake)
    return fake


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The background build, replaced: records which version it was started for."""
    started: list[str] = []

    async def build(version: Any, simulator: SimulatorVersion, suffix: str | None = None) -> None:
        started.append(version.label)

    monkeypatch.setattr(lifecycle, "build_and_export", build)
    return started


@pytest_asyncio.fixture(autouse=True)
async def fresh(database_service: DatabaseServiceSQL) -> None:
    """These tests' documents all need the same entries, so the same mash-up: none of it is left from another test."""
    from sqlalchemy import delete, update

    from compose_api.db.tables.environment_tables import ORMEnvironment, ORMEnvironmentVersion

    name = lifecycle.mash_up_name(NEEDED)
    async with database_service.async_sessionmaker() as session, session.begin():
        env = (await session.execute(select(ORMEnvironment).where(ORMEnvironment.name == name))).scalar_one_or_none()
        if env is not None:
            await session.execute(
                update(ORMEnvironment).where(ORMEnvironment.id == env.id).values(default_version_id=None)
            )
            await session.execute(delete(ORMEnvironmentVersion).where(ORMEnvironmentVersion.environment_id == env.id))
            await session.execute(delete(ORMEnvironment).where(ORMEnvironment.id == env.id))


@pytest.fixture
def signed_in() -> Iterator[FastAPI]:
    async def principal() -> AuthenticatedPrincipal:
        return USER

    api_app.dependency_overrides[get_optional_principal] = principal
    yield api_app
    api_app.dependency_overrides.pop(get_optional_principal, None)


def _document(tmp_path: Path, *addresses: str) -> tuple[str, bytes, str]:
    state = {f"p{i}": {"_type": "process", "address": a} for i, a in enumerate(addresses)}
    return ("doc.pbg", json.dumps({"state": state}).encode(), "application/json")


async def _submit(client: httpx.AsyncClient, tmp_path: Path, *addresses: str) -> httpx.Response:
    return await client.post("/simulation/run", files={"uploaded_file": _document(tmp_path, *addresses)})


def test_a_mash_up_is_named_by_its_entries_and_only_composable_ones_qualify() -> None:
    manifest = load_manifest()
    assert needed_entries([COPASI[6:], DOSE[6:]], manifest) == NEEDED
    name = lifecycle.mash_up_name(NEEDED)
    assert name == lifecycle.mash_up_name(set(NEEDED)) and len(name) == len("mash-") + 10
    assert lifecycle.composable(NEEDED, manifest) == []
    (listed,) = lifecycle.composable({"viva-tellurium"}, manifest)  # a catalog wrapper: no install, `listed`
    assert "does not say how it installs" in listed
    assert any("cannot be composed" in p for p in lifecycle.composable({"viva-pde-particle"}, manifest))


def test_declared_environments_cover_before_mash_ups() -> None:
    manifest = load_manifest()
    environments = load_environments()
    shared = next(e for e in environments.environments if e.kind == "shared")
    wide = EnvironmentSpec(name="mash-wide", kind="mash-up", python=shared.python, entries=sorted(shared.entries))
    assert covering_environment({"pbsim-common"}, manifest, environments, mash_ups=[wide]) is shared
    both = EnvironmentSpec(name="mash-both", kind="mash-up", python=shared.python, entries=sorted(NEEDED))
    assert covering_environment(NEEDED, manifest, environments, mash_ups=[wide, both]) is both
    assert covering_environment(NEEDED, manifest, environments) is None


@pytest.mark.asyncio
async def test_a_run_no_environment_covers_gets_a_mash_up_made_for_it(
    signed_in: FastAPI, database_service: DatabaseServiceSQL, locks: Locks, builds: list[str], tmp_path: Path
) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=signed_in), base_url="http://t") as client:
        first = await _submit(client, tmp_path, COPASI, DOSE)
        assert not (first.status_code == 400 and "violations" in first.text), first.text
        name = lifecycle.mash_up_name(NEEDED)
        assert len(locks.asked) == 1  # locked in the request (its build follows: see the test below)
        environments_db = database_service.get_environments_db()
        default = await environments_db.get_default(name)
        assert default is not None and default.state == VersionState.BUILDING and default.created_by == USER.subject
        assert '"viva-basic-processes" = { "git"' in (default.spec or {})["pixi_toml"]
        record = next(r for r in await environments_db.environments() if r.name == name)
        assert (record.kind, record.entries) == ("mash-up", sorted(NEEDED))

        again = await _submit(client, tmp_path, COPASI, DOSE)  # the same set: the same mash-up, not built again
        assert not (again.status_code == 400 and "violations" in again.text), again.text
        assert len(locks.asked) == 1

        covered = await _submit(client, tmp_path, COPASI)  # registry_env covers it, as before
        assert not (covered.status_code == 400 and "violations" in covered.text), covered.text
        assert len(locks.asked) == 1


@pytest.mark.asyncio
async def test_the_mash_up_made_for_a_run_is_built_after_the_response(
    database_service: DatabaseServiceSQL, locks: Locks, builds: list[str], tmp_path: Path
) -> None:
    from compose_api.api.routers import simulation as simulation_router

    path = tmp_path / "doc.pbg"
    path.write_bytes(_document(tmp_path, COPASI, DOSE)[1])
    tasks = BackgroundTasks()
    inferred = await simulation_router._inferred(path, SimulationFileType.PBG, USER, tasks)
    name = lifecycle.mash_up_name(NEEDED)
    assert (inferred.mash_up, inferred.version, inferred.simulator) == (name, 1, None)
    await tasks()
    assert builds == [f"{name}@1"]
    second = BackgroundTasks()
    assert (await simulation_router._inferred(path, SimulationFileType.PBG, USER, second)).mash_up == name
    await second()
    assert builds == [f"{name}@1"] and len(locks.asked) == 1  # used again, not locked or built again


@pytest.mark.asyncio
async def test_nothing_is_made_for_an_anonymous_caller_or_a_run_validation_refuses(
    http_api_client: httpx.AsyncClient, signed_in: FastAPI, locks: Locks, builds: list[str], tmp_path: Path
) -> None:
    api_app.dependency_overrides.pop(get_optional_principal, None)  # anonymous, through the real dependency
    anonymous = await _submit(http_api_client, tmp_path, COPASI, DOSE)
    assert anonymous.status_code == 401 and "sign in" in anonymous.json()["detail"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=signed_in), base_url="http://t") as client:
        signed_in.dependency_overrides[get_optional_principal] = lambda: USER
        unsafe = await _submit(client, tmp_path, COPASI, DOSE, "local:!os.system")
        unregistered = await _submit(client, tmp_path, COPASI, DOSE, "local:numpy.Solver")
    assert unsafe.status_code == 400 and unregistered.status_code == 400
    assert locks.asked == [] and builds == []


@pytest.mark.asyncio
async def test_entries_that_conflict_are_a_409_with_pixis_explanation(
    signed_in: FastAPI, database_service: DatabaseServiceSQL, locks: Locks, builds: list[str], tmp_path: Path
) -> None:
    locks.refuse = "Because pbsim-common depends on numpy<2 and viva-basic-processes on numpy>=2"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=signed_in), base_url="http://t") as client:
        refused = await _submit(client, tmp_path, COPASI, DOSE)
        again = await _submit(client, tmp_path, COPASI, DOSE)  # its failed first version answers, not a new lock
    assert refused.status_code == 409 and "numpy" in refused.json()["detail"]
    assert again.status_code == 409 and len(locks.asked) == 1 and builds == []


@pytest.mark.asyncio
async def test_at_most_two_mash_ups_are_made_at_a_time(
    database_service: DatabaseServiceSQL, locks: Locks, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def busy(_: Any) -> int:
        return lifecycle.MAX_MASH_UP_BUILDS

    monkeypatch.setattr(lifecycle, "_builds_under_way", busy)
    with pytest.raises(lifecycle.MashUpError) as refused:
        await lifecycle.mash_up_for(database_service, {"pbsim-common", "viva-basic-processes"}, USER.subject)
    assert refused.value.status == 429 and locks.asked == []


@pytest.mark.asyncio
async def test_an_administrator_makes_a_mash_ups_later_versions(
    database_service: DatabaseServiceSQL, locks: Locks, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D7.7: only the first version is made for a run; after that (here: after a conflict), an administrator."""
    from compose_api import dependencies
    from compose_api.api.routers import registry as registry_router
    from compose_api.authorization import get_caller
    from compose_api.config import override_settings

    locks.refuse = "a conflict"
    with pytest.raises(lifecycle.MashUpError):
        await lifecycle.mash_up_for(database_service, NEEDED, USER.subject)
    locks.refuse = None
    for service in ("get_required_simulation_service", "get_required_job_monitor"):
        monkeypatch.setattr(dependencies, service, lambda: None)
    built: list[str] = []

    async def build(version: Any, simulator: Any) -> None:
        built.append(version.label)

    monkeypatch.setattr(lifecycle, "build_version", build)

    async def no_uv(*_: Any) -> bool:
        return False

    from compose_api.environments import service as environment_service

    monkeypatch.setattr(environment_service, "export_uv", no_uv)
    admin = FastAPI()
    admin.include_router(registry_router.config.router, prefix=registry_router.config.prefix)

    @dataclass(frozen=True)
    class Admin:
        subject: str = "auth0|ops"
        roles: frozenset[str] = frozenset({"user", "env-admin"})

    async def caller() -> Admin:
        return Admin()

    admin.dependency_overrides[get_caller] = caller
    name = lifecycle.mash_up_name(NEEDED)
    with override_settings(environment_admin_role="env-admin"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=admin), base_url="http://t") as client:
            created = await client.post(f"/registry/environments/{name}/versions", json={"note": "again"})
    assert created.status_code == 201, created.text
    assert created.json()["number"] == 2 and built == [f"{name}@2"]
