"""Entry updates (docs/plan-entry-updates.md, step 1): a manifest entry flagged `updates` has its commit moved by an
environment administrator making a version, checked with GitHub, instead of by a pull request to the manifest."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.environments import lifecycle
from compose_api.environments import service as environment_service
from compose_api.registry import upstream
from compose_api.registry.manifest import Install, Manifest, RegistryEntry, load_manifest
from tests.environments.test_mash_up_creation import NEEDED, USER, Locks, fresh, locks  # noqa: F401

COMPLIANCE = Path(__file__).resolve().parents[2] / "compose_api" / "registry" / "compliance"
OLD, NEW, ELSEWHERE = "a" * 40, "b" * 40, "c" * 40
REPO = "https://github.com/example/thing"


def _entry(**changes: Any) -> RegistryEntry:
    fields: dict[str, Any] = {
        "id": "thing",
        "package": "thing",
        "source": REPO,
        "commit": OLD,
        "module_roots": ["thing"],
        "level": "tested",
        "install": Install(git=REPO, commit=OLD),
        "updates": "main",
    }
    return RegistryEntry.model_validate({**fields, **changes})


def test_only_a_git_install_can_follow_its_repository() -> None:
    with pytest.raises(ValueError, match="only a `git` install"):
        _entry(install=Install(pypi="thing", version="1.0"), commit=None, version="1.0")
    moved = _entry().at_commit(NEW)
    assert (moved.commit, moved.install and moved.install.commit) == (NEW, NEW)
    assert moved.install is not None and moved.install.git == REPO  # nothing else moves


def test_every_flagged_entry_has_compliance_cases_to_certify_a_new_commit() -> None:
    flagged = [e.id for e in load_manifest().entries if e.updates is not None]
    assert flagged, "viva-pde-particle is flagged (docs/plan-entry-updates.md, step 1)"
    for entry_id in flagged:
        cases = COMPLIANCE / entry_id
        assert cases.is_dir() and any(cases.iterdir()), f"{entry_id} has `updates` but no compliance cases"


def _github(routes: dict[str, httpx.Response]) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        path = request.url.path + (f"?{request.url.query.decode()}" if request.url.query else "")
        return routes.get(path, httpx.Response(404, json={"message": "Not Found"}))

    return httpx.AsyncClient(base_url="https://api.github.com", transport=httpx.MockTransport(answer))


def _repository(**more: httpx.Response) -> dict[str, httpx.Response]:
    return {"/repos/example/thing": httpx.Response(200, json={"default_branch": "main"}), **more}


@pytest.mark.asyncio
async def test_a_commit_on_the_default_branch_is_allowed_and_one_off_it_is_not() -> None:
    on_main = _repository(**{
        f"/repos/example/thing/compare/main...{NEW}": httpx.Response(200, json={"status": "behind"})
    })
    assert await upstream.allowed_commit(REPO, NEW, "main", _github(on_main)) == NEW
    off = _repository(**{f"/repos/example/thing/compare/main...{NEW}": httpx.Response(200, json={"status": "ahead"})})
    with pytest.raises(upstream.CommitRefusedError, match="not on"):
        await upstream.allowed_commit(REPO, NEW, "main", _github(off))
    with pytest.raises(upstream.CommitRefusedError, match="no commit"):
        await upstream.allowed_commit(REPO, NEW, "main", _github(_repository()))


@pytest.mark.asyncio
async def test_the_branch_name_stands_for_its_head_and_no_other_name_is_taken() -> None:
    head = _repository(**{"/repos/example/thing/commits/main": httpx.Response(200, json={"sha": NEW})})
    assert await upstream.allowed_commit(REPO, "main", "main", _github(head)) == NEW
    with pytest.raises(upstream.CommitRefusedError, match="full 40-character commit"):
        await upstream.allowed_commit(REPO, "dev", "main", _github(head))


@pytest.mark.asyncio
async def test_tags_allow_only_a_tagged_commit() -> None:
    tags = {
        "/repos/example/thing/tags?per_page=100": httpx.Response(200, json=[{"name": "v1.2.0", "commit": {"sha": NEW}}])
    }
    assert await upstream.allowed_commit(REPO, "v1.2.0", "tags", _github(tags)) == NEW
    assert await upstream.allowed_commit(REPO, NEW, "tags", _github(tags)) == NEW
    with pytest.raises(upstream.CommitRefusedError, match="release tag"):
        await upstream.allowed_commit(REPO, ELSEWHERE, "tags", _github(tags))


@pytest.mark.asyncio
async def test_github_unavailable_and_other_hosts() -> None:
    down = {"/repos/example/thing": httpx.Response(503)}
    with pytest.raises(upstream.UpstreamUnavailableError):
        await upstream.allowed_commit(REPO, NEW, "main", _github(down))
    with pytest.raises(upstream.CommitRefusedError, match="not a GitHub repository"):
        await upstream.allowed_commit("https://gitlab.com/example/thing", NEW, "main", _github({}))


@dataclass(frozen=True)
class _Admin:
    subject: str = "auth0|ops"
    roles: frozenset[str] = frozenset({"user", "env-admin"})


Post = Callable[[dict[str, Any]], Any]


@pytest.fixture
def post_version(
    database_service: DatabaseServiceSQL,
    locks: Locks,  # noqa: F811  (the fixture imported above)
    monkeypatch: pytest.MonkeyPatch,
) -> Post:
    """POST a version of the mash-up of NEEDED as an environment administrator; its build is not started."""
    from compose_api import dependencies
    from compose_api.api.routers import registry as registry_router
    from compose_api.authorization import get_caller
    from compose_api.config import override_settings

    for service in ("get_required_simulation_service", "get_required_job_monitor"):
        monkeypatch.setattr(dependencies, service, lambda: None)

    async def nothing(*_: Any) -> None:
        return None

    monkeypatch.setattr(lifecycle, "resolve_and_build", nothing)
    admin = FastAPI()
    admin.include_router(registry_router.config.router, prefix=registry_router.config.prefix)

    async def caller() -> _Admin:
        return _Admin()

    admin.dependency_overrides[get_caller] = caller

    async def post(body: dict[str, Any]) -> httpx.Response:
        await lifecycle.mash_up_for(database_service, NEEDED, USER.subject)  # its first version, made for a run
        with override_settings(environment_admin_role="env-admin"):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=admin), base_url="http://t") as client:
                return await client.post(f"/registry/environments/{lifecycle.mash_up_name(NEEDED)}/versions", json=body)

    return post


def _flag_pbsim_common(monkeypatch: pytest.MonkeyPatch) -> str:
    """pbsim-common, flagged `updates: main` for the test: its current commit."""
    manifest = load_manifest()
    flagged = Manifest(
        entries=[e.model_copy(update={"updates": "main"}) if e.id == "pbsim-common" else e for e in manifest.entries]
    )
    monkeypatch.setattr(environment_service, "load_manifest", lambda: flagged)
    entry = next(e for e in manifest.entries if e.id == "pbsim-common")
    assert entry.install is not None and entry.install.commit is not None
    return entry.install.commit


@pytest.mark.asyncio
async def test_an_administrator_makes_a_version_with_a_flagged_entry_moved(
    post_version: Post, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _flag_pbsim_common(monkeypatch)
    asked: list[tuple[str, str, str]] = []

    async def allowed(git_url: str, ref: str, updates: str, client: object = None) -> str:
        asked.append((git_url, ref, updates))
        return NEW

    monkeypatch.setattr(upstream, "allowed_commit", allowed)
    created = await post_version({"entries": {"pbsim-common": "main"}, "note": "pbsim_common's latest"})
    assert created.status_code == 201, created.text
    spec = created.json()["spec"]
    assert spec["moved"] == {"pbsim-common": {"from": before, "to": NEW}}
    [installed] = [e for e in spec["entries"] if e["id"] == "pbsim-common"]
    assert installed["install"]["commit"] == NEW and NEW in spec["pixi_toml"] and before not in spec["pixi_toml"]
    assert asked == [("https://github.com/biosimulations/pbsim_common", "main", "main")]


@pytest.mark.asyncio
async def test_what_cannot_move_is_refused(post_version: Post, monkeypatch: pytest.MonkeyPatch) -> None:
    unflagged = await post_version({"entries": {"pbsim-common": NEW}})
    assert unflagged.status_code == 422 and "pull request" in unflagged.json()["detail"]
    absent = await post_version({"entries": {"viva-pde-particle": NEW}})
    assert absent.status_code == 422 and "has no entry" in absent.json()["detail"]

    _flag_pbsim_common(monkeypatch)

    async def refused(*_: object, **__: object) -> str:
        raise upstream.CommitRefusedError("not on the default branch")

    monkeypatch.setattr(upstream, "allowed_commit", refused)
    off_branch = await post_version({"entries": {"pbsim-common": ELSEWHERE}})
    assert off_branch.status_code == 422 and "default branch" in off_branch.json()["detail"]

    async def down(*_: object, **__: object) -> str:
        raise upstream.UpstreamUnavailableError("GitHub answered 503")

    monkeypatch.setattr(upstream, "allowed_commit", down)
    assert (await post_version({"entries": {"pbsim-common": ELSEWHERE}})).status_code == 502


@pytest.mark.asyncio
async def test_the_manifests_own_commit_moves_nothing(post_version: Post, monkeypatch: pytest.MonkeyPatch) -> None:
    before = _flag_pbsim_common(monkeypatch)

    async def same(*_: object, **__: object) -> str:
        return before

    monkeypatch.setattr(upstream, "allowed_commit", same)
    created = await post_version({"entries": {"pbsim-common": before}})
    assert created.status_code == 201, created.text
    assert "moved" not in created.json()["spec"]
