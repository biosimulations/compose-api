"""The environments documents run in and their interface manifests (docs/plan-authoring.md): the configuration,
the generator's docker command, the served summaries and manifests, and the manifests committed so far."""

import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport

from compose_api.api.routers import registry as registry_router
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseService
from compose_api.registry import environments
from compose_api.registry.environments import (
    INTERFACES_VERSION,
    EnvironmentsFile,
    EnvironmentSpec,
    catalog_entries,
    composition_problems,
    load_environments,
    module_roots,
    read_manifest,
    summarize,
)
from compose_api.registry.generate import describe_command, prebuilt_pins, shared_image
from compose_api.registry.manifest import CurationLevel, Manifest, RegistryEntry, load_manifest
from tests.fixtures.postgres_fixtures import register_prebuilt

needs_pblang = pytest.mark.skipif(
    not Path(get_settings().pblang_python).exists(), reason="process-bigraph-lang is not installed (make pblang)"
)

PDE_IMAGE = "ghcr.io/example/pde@sha256:1"


def manifest_json(name: str, image: str | None, modules: list[str]) -> dict[str, Any]:
    return {
        "$schema": "https://biosimulations.github.io/process-bigraph-lang/schemas/pbg-interfaces-1.schema.json",
        "schema_version": INTERFACES_VERSION,
        "environment": {"name": name, "image": image, "process_bigraph": "1.8.5"},
        "components": [
            {
                "name": module.rsplit(".", 1)[-1].title(),
                "kind": "process",
                "address": f"local:!{module}.{module.rsplit('.', 1)[-1].title()}",
                "module": module,
                "config_schema": {"dt": {"_type": "float", "_default": 0.01}},
                "inputs": {"fields": "map[array[float]]"},
                "outputs": None,
                "dynamic_ports": False,
                "description": "A test process.",
            }
            for module in modules
        ],
        "errors": [{"module": "viva_pde_particle.broken", "error": "ImportError: no"}],
    }


@pytest.fixture
def manifests_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(environments, "MANIFESTS_DIR", tmp_path)
    (tmp_path / "viva-pde-particle.json").write_text(
        json.dumps(manifest_json("viva-pde-particle", PDE_IMAGE, ["viva_pde_particle.processes.fv", "elsewhere.x"]))
    )
    return tmp_path


def test_environments_file_names_each_environment_once_and_each_has_modules() -> None:
    config = load_environments()
    names = [e.name for e in config.environments]
    assert len(names) == len(set(names))
    assert {"registry_env", "viva-pde-particle"} <= set(names)
    for name in names:
        assert module_roots(name), f"no registry entry is in the {name!r} bundle"
    assert module_roots("viva-pde-particle") == ["viva_pde_particle"]
    assert config.describe.raw_url.startswith("https://raw.githubusercontent.com/biosimulations/process-bigraph-lang/")
    assert config.describe.raw_url.endswith("/process_bigraph_lang/v2/describe_env.py")


def test_registry_env_is_composed_of_entries_that_say_how_they_install() -> None:
    assert composition_problems(load_environments(), load_manifest()) == []
    spec = next(e for e in load_environments().environments if e.name == "registry_env")
    assert {"pbsim-common", "pb-multiscale-actin", "biosim-toolkit", "readdy"} <= set(spec.entries)


def _composition(entries: list[str], *, kind: str = "shared") -> EnvironmentsFile:
    return EnvironmentsFile.model_validate({
        "describe": {"source": "https://github.com/o/r", "ref": "a" * 40, "path": "d.py"},
        "environments": [{"name": "env", "kind": kind, "python": ["python"], "entries": entries}],
    })


def _entry(entry_id: str, **fields: object) -> RegistryEntry:
    return RegistryEntry.model_validate({
        "id": entry_id, "package": entry_id, "source": "https://example.org", "version": "1", "level": "tested",
        "module_roots": [entry_id.replace("-", "_")], "bundles": ["env"], **fields,
    })  # fmt: skip


def test_a_composition_that_cannot_be_built_is_explained() -> None:
    pinned = {"pypi": "a", "version": "1"}
    manifest = Manifest(
        entries=[
            _entry("a", install=pinned),
            _entry("a-again", install={"pypi": "A", "version": "2"}),  # the same distribution, by another name
            _entry("loose"),  # no `install`
            _entry("elsewhere", install={"pypi": "e", "version": "1"}, bundles=[]),
        ]
    )
    problems = composition_problems(_composition(["a", "a-again", "loose", "elsewhere", "ghost"]), manifest)
    assert any("'a' and 'a-again' both install a" in p for p in problems)
    assert any("'loose' does not say how it installs" in p for p in problems)
    assert any("no registry entry 'ghost'" in p for p in problems)
    assert any("differ from the entries bundled in it" in p for p in problems)  # `elsewhere` is not bundled in env
    assert composition_problems(_composition(["a"]), Manifest(entries=[_entry("a", install=pinned)])) == []
    prebuilt = composition_problems(
        _composition(["a"], kind="prebuilt"), Manifest(entries=[_entry("a", install=pinned)])
    )
    assert prebuilt == ["env: a prebuilt image is its owner's, so it lists no entries"]


def test_a_composition_must_list_what_its_entries_require() -> None:
    pinned = {"pypi": "a", "version": "1"}
    needs_b = _entry("a", install=pinned).model_copy(update={"requires": ["b"]})
    manifest = Manifest(entries=[needs_b, _entry("b", install={"pypi": "b", "version": "1"})])
    assert any("'a' requires ['b']" in p for p in composition_problems(_composition(["a"]), manifest))
    assert not any("requires" in p for p in composition_problems(_composition(["a", "b"]), manifest))


def test_the_viva_pde_particle_entry_is_runnable_only_in_its_own_image() -> None:
    entry = next(e for e in load_manifest().entries if e.id == "viva-pde-particle")
    assert entry.level == CurationLevel.TESTED and entry.evidence
    # not registry_env: a run naming no environment is inferred to its image (step 7a), and registry_env refuses it
    assert entry.bundles == ["viva-pde-particle"]


def test_the_deployment_pins_every_prebuilt_environment() -> None:
    pins = prebuilt_pins()
    for spec in load_environments().environments:
        if spec.kind == "prebuilt":
            assert spec.name in pins and "@sha256:" in pins[spec.name], f"{spec.name} is not pinned by digest"


def test_describe_command_runs_the_script_through_the_environments_python(tmp_path: Path) -> None:
    spec = EnvironmentSpec(
        name="viva-pde-particle", kind="prebuilt", python=["/bin/bash", "-c", 'exec python "$@"', "python"]
    )
    command = describe_command(spec, PDE_IMAGE, ["viva_pde_particle"], tmp_path)
    assert command[:2] == ["docker", "run"]
    assert command[command.index("-v") + 1] == f"{tmp_path}:/pblang:ro"
    assert command[command.index("--entrypoint") + 1] == "/bin/bash"
    image_at = command.index(PDE_IMAGE)
    assert command[image_at + 1 :] == [
        "-c", 'exec python "$@"', "python",
        "/pblang/describe_env.py", "viva_pde_particle", "--env-name", "viva-pde-particle", "--image", PDE_IMAGE,
    ]  # fmt: skip


def test_read_manifest_adds_each_components_registry_entry(manifests_dir: Path) -> None:
    manifest = read_manifest("viva-pde-particle")
    assert manifest is not None
    entries = {c.module: c.registry_entry for c in manifest.components}
    pde = entries["viva_pde_particle.processes.fv"]
    assert pde is not None and pde.id == "viva-pde-particle" and pde.level == CurationLevel.TESTED
    assert entries["elsewhere.x"] is None
    assert read_manifest("registry_env") is None  # none generated in this directory


def test_summaries_say_whether_the_manifest_matches_the_deployed_image(manifests_dir: Path) -> None:
    spec = next(e for e in load_environments().environments if e.name == "viva-pde-particle")
    assert summarize(spec, prebuilt={}) is None  # a prebuilt image this deployment does not offer is not listed
    current = summarize(spec, prebuilt={"viva-pde-particle": PDE_IMAGE})
    assert current is not None
    assert (current.simulator, current.components, current.errors, current.stale) == ("viva-pde-particle", 2, 1, False)
    assert current.process_bigraph == "1.8.5" and [e.id for e in current.entries] == ["viva-pde-particle"]
    moved = summarize(spec, prebuilt={"viva-pde-particle": "ghcr.io/example/pde@sha256:2"})
    assert moved is not None and moved.stale and moved.manifest_image == PDE_IMAGE

    shared = next(e for e in load_environments().environments if e.kind == "shared")
    listed = summarize(shared, prebuilt={})
    assert listed is not None
    assert listed.simulator is None and listed.image is None and listed.components == 0 and not listed.stale


@pytest_asyncio.fixture
async def client(manifests_dir: Path, database_service: DatabaseService) -> AsyncGenerator[httpx.AsyncClient]:
    app = FastAPI()
    app.include_router(registry_router.config.router, prefix=registry_router.config.prefix)
    await register_prebuilt(database_service, "viva-pde-particle", PDE_IMAGE)  # offered: it has a default (D8.3)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_routes_list_environments_and_serve_manifests(client: httpx.AsyncClient) -> None:
    listing = (await client.get("/registry/environments")).json()
    assert [e["name"] for e in listing] == ["registry_env", "viva-pde-particle"]

    response = await client.get("/registry/environments/viva-pde-particle/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["$schema"].endswith("pbg-interfaces-1.schema.json")
    assert body["schema_version"] == INTERFACES_VERSION
    first = body["components"][0]
    assert first["config_schema"] == {"dt": {"_type": "float", "_default": 0.01}}
    assert first["registry_entry"] == {"id": "viva-pde-particle", "level": "tested"}
    etag = response.headers["etag"]
    again = await client.get("/registry/environments/viva-pde-particle/manifest", headers={"If-None-Match": etag})
    assert again.status_code == 304

    assert (await client.get("/registry/environments/registry_env/manifest")).status_code == 404  # not generated
    assert (await client.get("/registry/environments/nope/manifest")).status_code == 404


@needs_pblang
@pytest.mark.asyncio
async def test_headers_render_each_module_and_each_class(client: httpx.AsyncClient) -> None:
    response = await client.get("/registry/environments/viva-pde-particle/headers")
    assert response.status_code == 200
    body = response.json()
    manifest = (await client.get("/registry/environments/viva-pde-particle/manifest")).json()
    first = manifest["components"][0]
    assert [m["module"] for m in body["modules"]] == sorted({c["module"] for c in manifest["components"]})
    texts = {m["module"]: m["text"] for m in body["modules"]}
    assert f"module {first['module']};" in texts[first["module"]]
    declaration = body["components"][first["address"]]
    assert declaration.startswith("/// A test process.\n")  # the description, as doc comments
    assert f'{first["kind"]} {first["name"]} at "{first["address"]}" {{' in declaration
    assert "module " not in declaration
    assert set(body["components"]) == {c["address"] for c in manifest["components"]}

    assert (await client.get("/registry/environments/registry_env/headers")).status_code == 404  # not generated
    assert (await client.get("/registry/environments/nope/headers")).status_code == 404


@pytest.mark.parametrize("path", sorted(environments.MANIFESTS_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_committed_manifests_are_current_and_their_components_are_registered(path: Path) -> None:
    spec = next((e for e in load_environments().environments if e.name == path.stem), None)
    assert spec is not None, f"{path.name} names no environment in environments.yaml"
    manifest = read_manifest(spec.name)
    assert manifest is not None and manifest.schema_version == INTERFACES_VERSION
    assert manifest.components, f"{path.name} lists no components"
    image = shared_image() if spec.kind == "shared" else prebuilt_pins().get(spec.name)
    assert (manifest.environment or {}).get("image") == image, f"{path.name} was read from another image: regenerate it"
    for component in manifest.components:
        assert component.registry_entry is not None, f"{component.address} belongs to no registry entry"


def test_catalog_entries_carry_their_level_and_the_environments_that_provide_them(manifests_dir: Path) -> None:
    entries = catalog_entries(prebuilt={"viva-pde-particle": PDE_IMAGE})
    levels = [e.level.rank for e in entries]
    assert levels == sorted(levels, reverse=True)  # most trusted first
    pde = next(e for e in entries if e.id == "viva-pde-particle")
    assert pde.level == CurationLevel.TESTED and [(x.name, x.components) for x in pde.environments] == [
        ("viva-pde-particle", 1)
    ]
    assert any(e.level == CurationLevel.LISTED and not e.environments for e in entries)  # catalog.yaml's, in none
    offered_nowhere = catalog_entries(prebuilt={})
    assert not next(e for e in offered_nowhere if e.id == "viva-pde-particle").environments


@pytest.mark.asyncio
async def test_route_lists_the_catalog(client: httpx.AsyncClient) -> None:
    listing = (await client.get("/registry/entries")).json()
    pde = next(e for e in listing if e["id"] == "viva-pde-particle")
    assert pde["level"] == "tested" and pde["environments"] == [{"name": "viva-pde-particle", "components": 1}]
