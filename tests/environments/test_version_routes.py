"""Environment versions through the API, step 4 (docs/plan-environment-versions.md): who may create and change them,
a version built in the background, the default an administrator chooses, and retiring.

The image work is the run path's own function (handlers.ensure_image), replaced here; a shared version's lock is
replaced too, so nothing reaches PyPI or a cluster."""

import hashlib
import uuid
from collections.abc import AsyncGenerator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport

from compose_api.api.routers import registry as registry_router
from compose_api.authorization import get_caller
from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.environments.versions import version_for
from compose_api.simulation import handlers
from compose_api.simulation.models import SimulatorVersion

ROLE = "env-admin"
PREBUILT = "viva-pde-particle"  # a prebuilt environment environments.yaml lists


@dataclass(frozen=True)
class FakeCaller:
    subject: str
    roles: frozenset[str] = field(default_factory=lambda: frozenset({"user"}))


ADMIN = FakeCaller("auth0|ops", frozenset({"user", ROLE}))
USER = FakeCaller("auth0|alice")


def _digest() -> str:
    return f"ghcr.io/example/pde@sha256:{uuid.uuid4().hex}{uuid.uuid4().hex}"


@dataclass
class Builds:
    """The run path's image function, replaced: records what it was asked for, and fails while ``failing``."""

    started: list[int] = field(default_factory=list)
    failing: bool = False

    async def __call__(self, simulator_version: SimulatorVersion, **_: object) -> None:
        self.started.append(simulator_version.database_id)
        if self.failing:
            raise RuntimeError("the build failed")


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> Iterator[Builds]:
    from compose_api import dependencies

    fake = Builds()
    monkeypatch.setattr(handlers, "ensure_image", fake)
    for name in ("get_required_simulation_service", "get_required_job_monitor"):
        monkeypatch.setattr(registry_router, name, lambda: None)
        monkeypatch.setattr(dependencies, name, lambda: None)  # compliance runs are only recorded and queued here
    with override_settings(environment_admin_role=ROLE):
        yield fake


@pytest_asyncio.fixture
async def app(database_service: DatabaseServiceSQL) -> AsyncGenerator[FastAPI]:
    app = FastAPI()
    app.include_router(registry_router.config.router, prefix=registry_router.config.prefix)
    yield app


def _as(app: FastAPI, caller: FakeCaller | None) -> httpx.AsyncClient:
    async def override() -> FakeCaller | None:
        return caller

    app.dependency_overrides[get_caller] = override
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_reading_is_public_and_changing_needs_the_administrator_role(app: FastAPI) -> None:
    body = {"image": _digest()}
    async with _as(app, None) as anonymous:
        assert (await anonymous.get(f"/registry/environments/{PREBUILT}/versions")).status_code == 200
        assert (await anonymous.post(f"/registry/environments/{PREBUILT}/versions", json=body)).status_code == 401
    async with _as(app, ADMIN) as admin:
        refused = await admin.post(f"/registry/environments/{PREBUILT}/versions", json=body)
        assert refused.status_code == 403 and "not configured" in refused.json()["detail"]  # no role set here
    with override_settings(environment_admin_role=ROLE):
        async with _as(app, USER) as user:
            for response in (
                await user.post(f"/registry/environments/{PREBUILT}/versions", json=body),
                await user.put(f"/registry/environments/{PREBUILT}/default", json={"number": 1}),
                await user.post(f"/registry/environments/{PREBUILT}/versions/1/retire"),
            ):
                assert response.status_code == 403, response.text
    async with _as(app, None) as anonymous:
        assert (await anonymous.get("/registry/environments/no-such-env/versions")).status_code == 404


@pytest.mark.asyncio
async def test_a_prebuilt_version_is_built_in_the_background_and_asking_again_answers_it(
    app: FastAPI, builds: Builds, database_service: DatabaseServiceSQL
) -> None:
    image = _digest()
    async with _as(app, ADMIN) as admin:
        created = await admin.post(f"/registry/environments/{PREBUILT}/versions", json={"image": image, "note": "t"})
        assert created.status_code == 201, created.text
        version = created.json()
        assert (version["state"], version["image"], version["created_by"]) == ("building", image, ADMIN.subject)
        assert builds.started == [version["simulator_id"]]  # the background task ran once the response was sent

        detail = (await admin.get(f"/registry/environments/{PREBUILT}/versions/{version['number']}")).json()
        assert detail["state"] == "ready" and detail["note"] == "t"

        again = await admin.post(f"/registry/environments/{PREBUILT}/versions", json={"image": image})
        assert again.status_code == 200 and again.json()["number"] == version["number"]
        assert builds.started == [version["simulator_id"]]  # a ready version is not built again

        listed = (await admin.get(f"/registry/environments/{PREBUILT}/versions")).json()
        assert listed["versions"][0]["number"] == version["number"]  # newest first


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"image": "ghcr.io/example/pde:latest"},  # not by digest
        {"image": None},
        {"libraries": [{"name": "six", "package_registry": "pypi"}]},
        {"resolved_at": "2026-10-25T00:00:00Z"},
    ],
)
async def test_a_prebuilt_version_is_an_image_by_digest_and_nothing_else(
    app: FastAPI, builds: Builds, body: dict[str, Any]
) -> None:
    async with _as(app, ADMIN) as admin:
        response = await admin.post(f"/registry/environments/{PREBUILT}/versions", json=body)
    assert response.status_code == 422, response.text
    assert builds.started == []


@pytest.mark.asyncio
async def test_a_failed_version_is_built_again_when_asked_again(app: FastAPI, builds: Builds) -> None:
    image = _digest()
    builds.failing = True
    async with _as(app, ADMIN) as admin:
        number = (await admin.post(f"/registry/environments/{PREBUILT}/versions", json={"image": image})).json()[
            "number"
        ]
        assert (await admin.get(f"/registry/environments/{PREBUILT}/versions/{number}")).json()["state"] == "failed"
        refused = await admin.put(f"/registry/environments/{PREBUILT}/default", json={"number": number})
        assert refused.status_code == 409  # only a ready version can be the default

        builds.failing = False
        again = await admin.post(f"/registry/environments/{PREBUILT}/versions", json={"image": image})
        assert again.status_code == 200 and again.json()["state"] == "building"
        assert (await admin.get(f"/registry/environments/{PREBUILT}/versions/{number}")).json()["state"] == "ready"
    assert len(builds.started) == 2


@pytest.mark.asyncio
async def test_the_chosen_default_is_what_runs_get_and_it_cannot_be_retired(
    app: FastAPI, builds: Builds, database_service: DatabaseServiceSQL
) -> None:
    chosen, other = _digest(), _digest()
    async with _as(app, ADMIN) as admin:
        first = (await admin.post(f"/registry/environments/{PREBUILT}/versions", json={"image": chosen})).json()
        second = (await admin.post(f"/registry/environments/{PREBUILT}/versions", json={"image": other})).json()
        made = await admin.put(f"/registry/environments/{PREBUILT}/default", json={"number": first["number"]})
        assert made.status_code == 200 and made.json()["number"] == first["number"]

        # the administrator's choice is what runs get
        version, simulator = await version_for(database_service, PREBUILT)
        assert (version.number, simulator.database_id) == (first["number"], first["simulator_id"])
        listed = (await admin.get(f"/registry/environments/{PREBUILT}/versions")).json()
        assert (listed["default"], listed["default_source"]) == (first["number"], "api")

        assert (
            await admin.post(f"/registry/environments/{PREBUILT}/versions/{first['number']}/retire")
        ).status_code == 409
        retired = await admin.post(f"/registry/environments/{PREBUILT}/versions/{second['number']}/retire")
        assert retired.status_code == 200 and retired.json()["state"] == "retired"


@dataclass
class Locks:
    """The lock Job, replaced: returns ``text`` (a distinct lock per request unless ``same``), or refuses."""

    refuse: str | None = None
    same: bool = False
    text: str = "version: 7\n"  # the lock every request gets while `same`
    asked: list[str] = field(default_factory=list)

    async def __call__(self, toml: str, pixi_image: str, suffix: str) -> str:
        from compose_api.simulation.build_k8s import LockFailedError

        self.asked.append(toml)
        if self.refuse is not None:
            raise LockFailedError(self.refuse)
        return self.text if self.same else f"version: 7\n# {uuid.uuid4().hex}\n"


@pytest.fixture
def locks(monkeypatch: pytest.MonkeyPatch) -> Locks:
    from compose_api.simulation import build_k8s

    fake = Locks()
    monkeypatch.setattr(build_k8s, "lock_composed", fake)
    return fake


@pytest.mark.asyncio
async def test_a_composed_version_resolves_in_the_background_then_builds(
    app: FastAPI, builds: Builds, locks: Locks, database_service: DatabaseServiceSQL
) -> None:
    async with _as(app, ADMIN) as admin:
        created = await admin.post("/registry/environments/registry_env/versions", json={"note": "pixi"})
        assert created.status_code == 201, created.text
        version = created.json()
        # answered before the lock: resolving, with no simulator yet, runtime contract 2
        assert (version["state"], version["simulator_id"], version["runtime_contract"]) == ("resolving", None, 2)
        assert version["spec"]["pixi_image"].startswith("ghcr.io/prefix-dev/pixi@sha256:")
        assert '"libvcell" = "==0.0.24"' in version["spec"]["pixi_toml"]
        assert {e["id"] for e in version["spec"]["entries"]} >= {"pbsim-common", "readdy"}
        detail = (await admin.get(f"/registry/environments/registry_env/versions/{version['number']}")).json()
    # the background task has run: locked, defined, built
    assert locks.asked == [version["spec"]["pixi_toml"]]
    assert detail["state"] == "ready" and detail["simulator_id"] is not None
    assert detail["lock"].startswith("version: 7\n") and detail["lock_sha256"]
    assert builds.started == [detail["simulator_id"]]
    simulator = await database_service.get_simulator_db().get_simulator(detail["simulator_id"])
    lock_hash = hashlib.sha256(detail["lock"].encode()).hexdigest()
    # the lock's hash is in its definition (the lock itself is built beside it): the lock is the version's identity
    assert simulator is not None and lock_hash in simulator.container_def.representation
    assert detail["spec"]["runner"].startswith('"""The entry point')  # it is built, and rebuilt, with this runner


@pytest.mark.asyncio
async def test_a_composition_that_does_not_resolve_fails_with_pixis_explanation(
    app: FastAPI, builds: Builds, locks: Locks
) -> None:
    locks.refuse = "No solution: process-bigraph ==1.9.1 conflicts with process-bigraph ==1.0.5"
    async with _as(app, ADMIN) as admin:
        number = (await admin.post("/registry/environments/registry_env/versions", json={})).json()["number"]
        detail = (await admin.get(f"/registry/environments/registry_env/versions/{number}")).json()
    assert detail["state"] == "failed" and detail["simulator_id"] is None
    assert "do not resolve together" in detail["failure"] and "conflicts with" in detail["failure"]
    assert builds.started == []


@pytest.mark.asyncio
async def test_a_version_that_resolves_to_an_existing_lock_says_which(
    app: FastAPI, builds: Builds, locks: Locks
) -> None:
    locks.same = True
    async with _as(app, ADMIN) as admin:
        # different dates (so different workspaces and definitions) that lock the same: the lock is the identity
        first = (
            await admin.post(
                "/registry/environments/registry_env/versions", json={"resolved_at": "2026-10-20T00:00:00"}
            )
        ).json()["number"]
        again = (
            await admin.post(
                "/registry/environments/registry_env/versions", json={"resolved_at": "2026-10-21T00:00:00"}
            )
        ).json()["number"]
        detail = (await admin.get(f"/registry/environments/registry_env/versions/{again}")).json()
    assert again == first + 1
    assert detail["state"] == "failed" and f"same lock as registry_env@{first}" in detail["failure"]
    assert len(builds.started) == 1


@pytest.mark.asyncio
async def test_a_composed_environment_takes_a_date_not_libraries_or_an_image(
    app: FastAPI, builds: Builds, locks: Locks
) -> None:
    """A library list (the retired shared uv path, D8.5) is refused as an unknown field; `preview` is gone."""
    async with _as(app, ADMIN) as admin:
        listed = await admin.post("/registry/environments/registry_env/versions", json={"libraries": [{"name": "six"}]})
        assert listed.status_code == 422 and "libraries" in listed.text
        imaged = await admin.post("/registry/environments/registry_env/versions", json={"image": _digest()})
        assert imaged.status_code == 422 and "composed from its registry entries" in imaged.json()["detail"]
        assert (await admin.post("/registry/environments/registry_env/versions/preview", json={})).status_code in (
            404,
            405,
        )
    assert locks.asked == []


@pytest.mark.asyncio
async def test_a_version_exports_the_files_that_recreate_it(app: FastAPI, builds: Builds, locks: Locks) -> None:
    async with _as(app, ADMIN) as admin:
        number = (await admin.post("/registry/environments/registry_env/versions", json={})).json()["number"]
    async with _as(app, None) as anonymous:  # public, as reading a version is
        exported = await anonymous.get(f"/registry/environments/registry_env/versions/{number}/export")
        assert exported.status_code == 200, exported.text
        body = exported.json()
        assert body["format"] == "pixi" and set(body["files"]) == {"pixi.toml", "pixi.lock"}
        assert body["files"]["pixi.lock"].startswith("version: 7\n") and "[workspace]" in body["files"]["pixi.toml"]
        wrong = await anonymous.get(f"/registry/environments/registry_env/versions/{number}/export?format=requirements")
        assert wrong.status_code == 409 and "exports as pixi" in wrong.json()["detail"]
        unknown = await anonymous.get(f"/registry/environments/registry_env/versions/{number}/export?format=conda")
        assert unknown.status_code == 409
    async with _as(app, ADMIN) as admin:
        image = (await admin.post(f"/registry/environments/{PREBUILT}/versions", json={"image": _digest()})).json()
    async with _as(app, None) as anonymous:
        prebuilt = await anonymous.get(f"/registry/environments/{PREBUILT}/versions/{image['number']}/export")
        assert prebuilt.status_code == 409 and "no lock to export" in prebuilt.json()["detail"]


@pytest.mark.asyncio
async def test_a_composition_without_conda_also_exports_as_uv(
    app: FastAPI, builds: Builds, locks: Locks, monkeypatch: pytest.MonkeyPatch
) -> None:
    from compose_api.environments import uv_export
    from compose_api.simulation import build_k8s

    projects: list[str] = []
    answer = {"lock": 'version = 1\n\n[[package]]\nname = "registry-env"\nversion = "0"\nsource = { virtual = "." }\n'}

    async def uv_lock(project: str, pixi_image: str, suffix: str) -> str:
        projects.append(project)
        return answer["lock"]

    monkeypatch.setattr(build_k8s, "uv_lock", uv_lock)

    async def create() -> int:
        async with _as(app, ADMIN) as admin:
            number: int = (await admin.post("/registry/environments/registry_env/versions", json={})).json()["number"]
            return number

    async def export_uv(number: int) -> httpx.Response:
        async with _as(app, None) as anonymous:
            return await anonymous.get(f"/registry/environments/registry_env/versions/{number}/export?format=uv")

    refused = await export_uv(await create())
    assert refused.status_code == 409 and "needs packages from conda-forge" in refused.json()["detail"]
    assert projects == []  # registry_env needs readdy: no uv form is attempted

    monkeypatch.setattr(uv_export, "needs_conda", lambda spec: False)
    exported = await export_uv(await create())
    assert exported.status_code == 200, exported.text
    assert set(exported.json()["files"]) == {"pyproject.toml", "uv.lock"} and len(projects) == 1

    answer["lock"] += '\n[[package]]\nname = "cffi"\nversion = "2.1.1"\n'  # uv arrives elsewhere: not kept
    missing = await export_uv(await create())
    assert missing.status_code == 409 and "has not been made" in missing.json()["detail"]


# --- compliance (docs/plan-environment-composition.md, step 5b) ---------------------------------------------------


def _passing_results(case_dir: Path) -> dict[str, object]:
    """What a run of a pbsim-common case emits when it matches its reference exactly."""
    rows = [line.split(",") for line in (case_dir / "reference.csv").read_text().splitlines()]
    header, body = rows[0], rows[1:]
    result = {
        "time": [float(r[0]) for r in body],
        "columns": header[1:],
        "values": [[float(v) for v in r[1:]] for r in body],
    }
    return {"emitter": [{"result": result}]}


@pytest.mark.asyncio
async def test_a_ready_composed_version_runs_its_entries_cases_and_reports_their_levels(
    app: FastAPI, builds: Builds, locks: Locks, database_service: DatabaseServiceSQL, monkeypatch: pytest.MonkeyPatch
) -> None:
    from compose_api import dependencies
    from compose_api.environments import compliance, compliance_runs

    for name in ("get_required_simulation_service", "get_required_job_monitor"):
        monkeypatch.setattr(dependencies, name, lambda: None)  # runs are only recorded and queued here
    async with _as(app, ADMIN) as admin:
        number = (await admin.post("/registry/environments/registry_env/versions", json={})).json()["number"]
    version = await database_service.get_environments_db().get_by_number("registry_env", number)
    assert version is not None and version.state == "ready"

    async def report() -> dict[str, Any]:
        async with _as(app, None) as anonymous:  # public, as reading a version is
            response = await anonymous.get(f"/registry/environments/registry_env/versions/{number}/compliance")
            assert response.status_code == 200, response.text
            body: dict[str, Any] = response.json()
            return body

    # submitted once the version was ready: pbsim-common's cases are running in it; entries without cases are untested
    pending = {e["entry"]: e for e in (await report())["entries"]}
    assert pending["pbsim-common"]["level"] == "pending"
    assert {c["case"] for c in pending["pbsim-common"]["cases"]} >= {"copasi-phase-cycle", "tellurium-phase-cycle"}
    assert pending["biosim-toolkit"]["level"] == "untested" and pending["biosim-toolkit"]["cases"] == []
    simulation_id = pending["pbsim-common"]["cases"][0]["simulation_id"]
    row = await database_service.get_simulator_db().get_simulation_row(simulation_id)
    assert row is not None and row.simulation.environment_version_id == version.database_id  # run in that version
    async with _as(app, None) as anonymous:  # its runs say when it was last used (D7.8)
        listed = (await anonymous.get("/registry/environments/registry_env/versions")).json()["versions"]
    used = {v["number"]: v["last_used_at"] for v in listed}
    assert used[number] is not None  # other tests share the database, so other versions may have runs too
    assert row.simulation.labels["source"] == "compliance" and row.simulation.labels["compliance"].startswith(
        "pbsim-common/"
    )

    # the runs finish and match their references: evaluated as the report is read
    cases = {c.name: c for c in compliance.load_cases("pbsim-common")}
    runs = {
        r.simulation_id: r.case
        for r in await database_service.get_environments_db().compliance_runs(version.database_id)
    }

    async def finished(ids: list[int]) -> dict[int, str]:
        return dict.fromkeys(ids, "completed")

    monkeypatch.setattr(database_service.get_simulator_db(), "get_simulation_statuses", finished)
    by_experiment: dict[str, str] = {}
    original = database_service.get_simulator_db().get_simulations_experiment_id

    async def experiment_id(simulation_id: int) -> str:
        found = await original(simulation_id=simulation_id)
        by_experiment[found] = runs[simulation_id]
        return found

    monkeypatch.setattr(database_service.get_simulator_db(), "get_simulations_experiment_id", experiment_id)

    def results(experiment_dir: Path) -> dict[str, object]:
        directory = cases[by_experiment[experiment_dir.name.removeprefix("experiment-")]].directory
        assert directory is not None
        return _passing_results(directory)

    monkeypatch.setattr(compliance_runs, "_results", results)
    tested = {e["entry"]: e for e in (await report())["entries"]}
    assert tested["pbsim-common"]["level"] == "tested"
    assert all(c["state"] == "passed" for c in tested["pbsim-common"]["cases"])

    # a generic check's failure refuses that component alone; the entry's level stands
    component = "pbsim_common.comparison.MSEComparison"
    await database_service.get_environments_db().set_findings(
        version.database_id,
        [{"component": component, "check": "step-outputs-replace", "severity": "fail", "detail": "x"}],
    )
    refused = await report()
    assert refused["refused"] == [component]
    assert {e["entry"]: e["level"] for e in refused["entries"]}["pbsim-common"] == "tested"

    # run again: the cases are pending again, then a run that fails is an error
    async with _as(app, ADMIN) as admin:
        again = await admin.post(f"/registry/environments/registry_env/versions/{number}/compliance")
        assert again.status_code == 202, again.text

    async def failed(ids: list[int]) -> dict[int, str]:
        return dict.fromkeys(ids, "failed")

    monkeypatch.setattr(database_service.get_simulator_db(), "get_simulation_statuses", failed)
    errored = {e["entry"]: e for e in (await report())["entries"]}
    assert errored["pbsim-common"]["level"] == "failed"
    assert errored["pbsim-common"]["cases"][0]["failures"] == ["the run ended failed"]


@pytest.mark.asyncio
async def test_compliance_runs_only_for_a_ready_composed_version(app: FastAPI, builds: Builds) -> None:
    async with _as(app, ADMIN) as admin:
        image = (await admin.post(f"/registry/environments/{PREBUILT}/versions", json={"image": _digest()})).json()
        refused = await admin.post(f"/registry/environments/{PREBUILT}/versions/{image['number']}/compliance")
    assert refused.status_code == 409 and "not a ready composed version" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_admission_follows_what_the_version_certifies(
    app: FastAPI, builds: Builds, locks: Locks, database_service: DatabaseServiceSQL, tmp_path: Path
) -> None:
    """Step 5c: the standing of the version a run will use, from its findings and its case runs, decides first."""
    import json

    from compose_api.environments.admission import standing_for
    from compose_api.registry.validation import AddressPolicy, SubmissionRejectedError, validate_submission
    from compose_api.simulation.models import SimulationFileType

    async with _as(app, ADMIN) as admin:
        number = (await admin.post("/registry/environments/registry_env/versions", json={})).json()["number"]
    environments_db = database_service.get_environments_db()
    version = await environments_db.get_by_number("registry_env", number)
    assert version is not None
    mse = "pbsim_common.comparison.MSEComparison"
    await environments_db.set_findings(
        version.database_id, [{"component": mse, "check": "step-outputs-replace", "severity": "fail", "detail": "sums"}]
    )
    standing = await standing_for(database_service, "registry_env", number)
    assert standing is not None and standing.label == f"registry_env@{number}"
    assert standing.members is not None and {"pbsim-common", "readdy"} <= standing.members
    assert standing.levels["pbsim-common"] == "pending" and standing.refused == {mse: "sums"}

    def submit(*addresses: str) -> None:
        state = {f"s{i}": {"_type": "step", "address": a} for i, a in enumerate(addresses)}
        path = tmp_path / "doc.pbg"
        path.write_text(json.dumps({"state": state}))
        validate_submission(path, SimulationFileType.PBG, AddressPolicy.ENFORCE, standing=standing)

    submit("local:pbsim_common.simulators.copasi_process.CopasiUTCStep")  # pending: the manifest's level stands
    with pytest.raises(SubmissionRejectedError) as refused:
        submit(f"local:{mse}")
    assert f"refused in registry_env@{number}: sums" in refused.value.violations[0].reason

    for run in await environments_db.compliance_runs(version.database_id):
        await environments_db.set_compliance_outcome(run.id, "failed", ["off"])
    standing = await standing_for(database_service, "registry_env", number)
    assert standing is not None and standing.levels["pbsim-common"] == "failed"
    with pytest.raises(SubmissionRejectedError) as failed:
        submit("local:pbsim_common.simulators.copasi_process.CopasiUTCStep")
    assert "failed its compliance cases" in failed.value.violations[0].reason


@pytest.mark.asyncio
async def test_a_lock_whose_version_failed_to_build_can_be_made_again(
    app: FastAPI, builds: Builds, locks: Locks
) -> None:
    """registry_env@2 failed to build on 0.7.43 (its definition overran one environment string); a version is its
    lock, but a failed one must not stand in the way of making that lock again."""
    locks.same, locks.text = True, f"version: 7\n# its own {uuid.uuid4().hex}\n"
    builds.failing = True
    async with _as(app, ADMIN) as admin:
        url = "/registry/environments/registry_env/versions"
        failed = (await admin.post(url, json={"resolved_at": "2026-10-20T00:00:00"})).json()["number"]
        builds.failing = False
        again = (await admin.post(url, json={"resolved_at": "2026-10-21T00:00:00"})).json()["number"]
        first = (await admin.get(f"{url}/{failed}")).json()
        retried = (await admin.get(f"{url}/{again}")).json()
    assert first["state"] == "failed"
    assert retried["state"] == "ready" and retried["failure"] is None, retried["failure"]
    assert retried["lock_sha256"] == first["lock_sha256"]


@pytest.mark.asyncio
async def test_a_mash_up_the_database_holds_is_listed_with_its_entries(
    app: FastAPI, database_service: DatabaseServiceSQL
) -> None:
    """D7.9: environments come from the database too; a mash-up, which no file declares, is listed with its entries
    and its versions can be read. (Step 7b creates them; here one is made directly.)"""
    from compose_api.api.routers import registry as registry_router_module
    from compose_api.db.tables.environment_tables import ORMEnvironment

    async with database_service.async_sessionmaker() as session, session.begin():
        session.add(ORMEnvironment(name="mash-0123456789", kind="mash-up", entries=["pbsim-common", "tellurium"]))
    listing = FastAPI()
    listing.include_router(registry_router_module.config.router, prefix=registry_router_module.config.prefix)
    async with _as(listing, None) as anonymous:
        environments = {e["name"]: e for e in (await anonymous.get("/registry/environments")).json()}
        versions = await anonymous.get("/registry/environments/mash-0123456789/versions")
        unknown = await anonymous.get("/registry/environments/mash-nothing/versions")
    mash_up = environments["mash-0123456789"]
    assert mash_up["kind"] == "mash-up" and mash_up["components"] == 0  # no version built yet
    assert [e["id"] for e in mash_up["entries"]] == ["pbsim-common", "tellurium"]
    assert next(iter(environments)) == "registry_env"  # the declared ones come first, as before
    assert versions.status_code == 200 and versions.json()["kind"] == "mash-up" and versions.json()["versions"] == []
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_a_version_lists_how_its_packages_differ_from_another(
    app: FastAPI, builds: Builds, database_service: DatabaseServiceSQL
) -> None:
    """`?against=` compares what the two images installed, by name as PyPI compares names (webapp-admin step 3)."""
    environments_db = database_service.get_environments_db()
    versions = f"/registry/environments/{PREBUILT}/versions"
    async with _as(app, ADMIN) as admin:
        numbers = []
        for installed in ("numpy==2.3.1\nPyYAML==6.0.2\nsix==1.16.0\n", "numpy==2.3.4\npyyaml==6.0.2\nscipy==1.16.0\n"):
            created = (await admin.post(versions, json={"image": _digest()})).json()
            await environments_db.set_contents(created["database_id"], installed, {"components": []})
            numbers.append(created["number"])
        older, newer = numbers
        diffed = await admin.get(f"{versions}/{newer}", params={"against": older})
        assert diffed.status_code == 200, diffed.text
        assert diffed.json()["against"] == older
        assert diffed.json()["changes"] == [
            {"name": "numpy", "before": "2.3.1", "after": "2.3.4"},
            {"name": "scipy", "before": None, "after": "1.16.0"},
            {"name": "six", "before": "1.16.0", "after": None},
        ]  # PyYAML and pyyaml are one package, unchanged
        plain = (await admin.get(f"{versions}/{newer}")).json()
        assert plain["changes"] is None and plain["against"] is None

        unread = (await admin.post(versions, json={"image": _digest()})).json()
        await environments_db.set_contents(unread["database_id"], None, {"components": []})
        refused = await admin.get(f"{versions}/{newer}", params={"against": unread["number"]})
        assert refused.status_code == 409 and f"@{unread['number']}" in refused.json()["detail"]
        missing = await admin.get(f"{versions}/{newer}", params={"against": 99999})
        assert missing.status_code == 404
