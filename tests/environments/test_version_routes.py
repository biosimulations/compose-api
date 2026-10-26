"""Environment versions through the API, step 4 (docs/plan-environment-versions.md): who may create and change them,
a version built in the background, the default an administrator chooses, and retiring.

The image work is the run path's own function (handlers.ensure_image), replaced here; a shared version's lock is
replaced too, so nothing reaches PyPI or a cluster."""

import datetime
import uuid
from collections.abc import AsyncGenerator, Iterator
from dataclasses import dataclass, field
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
from compose_api.environments import service as environment_service
from compose_api.environments.lock import Lock, SharedSpec
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
    fake = Builds()
    monkeypatch.setattr(handlers, "ensure_image", fake)
    for name in ("get_required_simulation_service", "get_required_job_monitor"):
        monkeypatch.setattr(registry_router, name, lambda: None)
    with override_settings(environment_admin_role=ROLE):
        yield fake


@pytest.fixture
def uv_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """registry_env as it was before it listed its entries: a shared environment whose versions are uv locks (the path
    docs/plan-environment-composition.md retires in step 8)."""
    monkeypatch.setattr(environment_service, "is_composed", lambda spec: False)


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
                await user.post(f"/registry/environments/{PREBUILT}/versions/preview", json={}),
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

        # the deployment pins something else: an administrator's choice is not overridden by it
        with override_settings(prebuilt_simulators={PREBUILT: _digest()}):
            version, simulator = await version_for(database_service, PREBUILT)
        assert (version.number, simulator.database_id) == (first["number"], first["simulator_id"])
        listed = (await admin.get(f"/registry/environments/{PREBUILT}/versions")).json()
        assert (listed["default"], listed["default_source"]) == (first["number"], "api")

        assert (
            await admin.post(f"/registry/environments/{PREBUILT}/versions/{first['number']}/retire")
        ).status_code == 409
        retired = await admin.post(f"/registry/environments/{PREBUILT}/versions/{second['number']}/retire")
        assert retired.status_code == 200 and retired.json()["state"] == "retired"


@pytest.mark.asyncio
async def test_a_default_made_before_locks_is_compared_by_what_its_image_installed(
    app: FastAPI, builds: Builds, database_service: DatabaseServiceSQL, monkeypatch: pytest.MonkeyPatch, uv_path: None
) -> None:
    lock = "numpy==2.5.4\npbest @ git+https://github.com/biosimulations/pbest@a4713e9\n"

    async def compile_lock(spec: SharedSpec, resolved_at: datetime.datetime) -> Lock:
        return Lock(text=lock, resolved_at=resolved_at.replace(tzinfo=None))

    monkeypatch.setattr(environment_service, "compile_lock", compile_lock)
    default, _ = await version_for(database_service, None)  # adopted from the deployment: no lock
    async with _as(app, ADMIN) as admin:
        unread_response = await admin.post("/registry/environments/registry_env/versions/preview", json={})
        assert unread_response.status_code == 200, unread_response.text
        unread = unread_response.json()
        assert (unread["against"], unread["against_basis"], unread["changes"]) == (None, None, [])

        installed = "numpy==2.4.0\npbest==0.6.5\n"  # read back from its image: a git install shows its version
        await database_service.get_environments_db().set_contents(default.database_id, installed, None)
        preview = (await admin.post("/registry/environments/registry_env/versions/preview", json={})).json()
    assert (preview["against"], preview["against_basis"]) == (default.number, "installed")
    assert preview["changes"] == [
        {"name": "numpy", "before": "2.4.0", "after": "2.5.4"},
        {"name": "pbest", "before": "0.6.5", "after": "git+https://github.com/biosimulations/pbest@a4713e9"},
    ]


@pytest.mark.asyncio
async def test_a_shared_version_is_its_lock_and_a_preview_shows_what_would_change(
    app: FastAPI, builds: Builds, monkeypatch: pytest.MonkeyPatch, uv_path: None
) -> None:
    locks = {"old": "numpy==2.4.0\nsix==1.10.0\n", "new": "numpy==2.5.4\nsix==1.10.0\nlibvcell==0.0.24\n"}
    use = {"lock": locks["old"]}

    async def compile_lock(spec: SharedSpec, resolved_at: datetime.datetime) -> Lock:
        return Lock(text=use["lock"], resolved_at=resolved_at.replace(tzinfo=None))

    monkeypatch.setattr(environment_service, "compile_lock", compile_lock)
    async with _as(app, ADMIN) as admin:
        created = await admin.post("/registry/environments/registry_env/versions", json={"note": "first lock"})
        assert created.status_code == 201, created.text
        number = created.json()["number"]
        detail = (await admin.get(f"/registry/environments/registry_env/versions/{number}")).json()
        assert detail["lock"] == locks["old"] and detail["origin"] == "registry"
        assert detail["spec"] == SharedSpec.from_registry().as_json()
        assert detail["state"] == "ready"
        assert (
            await admin.put("/registry/environments/registry_env/default", json={"number": number})
        ).status_code == 200

        same = (await admin.post("/registry/environments/registry_env/versions/preview", json={})).json()
        assert (same["existing"], same["against"], same["changes"]) == (number, number, [])

        use["lock"] = locks["new"]
        preview = (await admin.post("/registry/environments/registry_env/versions/preview", json={})).json()
        assert preview["existing"] is None and preview["against"] == number and preview["against_basis"] == "lock"
        assert preview["changes"] == [
            {"name": "libvcell", "before": None, "after": "0.0.24"},
            {"name": "numpy", "before": "2.4.0", "after": "2.5.4"},
        ]

        custom = await admin.post(
            "/registry/environments/registry_env/versions",
            json={"libraries": [{"name": "six", "version": "1.10.0", "package_registry": "pypi"}]},
        )
        assert custom.status_code == 201 and custom.json()["origin"] == "custom"
        refused = await admin.post("/registry/environments/registry_env/versions", json={"image": _digest()})
        assert refused.status_code == 422


# --- composed versions (docs/plan-environment-composition.md, step 4) ---------------------------------------------


@dataclass
class Locks:
    """The lock Job, replaced: returns ``text`` (a distinct lock per request unless ``same``), or refuses."""

    refuse: str | None = None
    same: bool = False
    asked: list[str] = field(default_factory=list)

    async def __call__(self, toml: str, pixi_image: str, suffix: str) -> str:
        from compose_api.simulation.build_k8s import LockFailedError

        self.asked.append(toml)
        if self.refuse is not None:
            raise LockFailedError(self.refuse)
        return "version: 7\n" + ("" if self.same else f"# {uuid.uuid4().hex}\n")


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
    assert (
        simulator is not None and detail["lock"] in simulator.container_def.representation
    )  # the lock is its identity


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
async def test_a_composed_environment_takes_a_date_not_libraries_images_or_a_preview(
    app: FastAPI, builds: Builds, locks: Locks
) -> None:
    async with _as(app, ADMIN) as admin:
        for body in ({"libraries": [{"name": "six", "package_registry": "pypi"}]}, {"image": _digest()}):
            refused = await admin.post("/registry/environments/registry_env/versions", json=body)
            assert refused.status_code == 422 and "composed from its registry entries" in refused.json()["detail"]
        preview = await admin.post("/registry/environments/registry_env/versions/preview", json={})
        assert preview.status_code == 422 and "resolved in a Job" in preview.json()["detail"]
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
