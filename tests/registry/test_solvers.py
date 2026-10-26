"""registry/solvers.yaml: every solver names an environment this service has, and a class that environment's image
provides (its read-back, docs/plan-environment-composition.md D8.4), so `sedml translate` can fill the role with it
(docs/plan-sedml.md, phase 2)."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from compose_api.api.routers import registry as registry_router
from compose_api.environments.manifests import annotated
from compose_api.registry.environments import InterfaceManifest, load_environments
from compose_api.registry.solvers import load_solvers, solver

# what registry_env@5's image provides, as read back on 2026-10-26 (the test database's registry_env manifest)
READ_BACK = Path(__file__).parents[1] / "fixtures" / "resources" / "registry_env.interfaces.json"


def _manifest(environment: str) -> InterfaceManifest | None:
    return annotated(json.loads(READ_BACK.read_text())) if environment == "registry_env" else None


def _key(address: str) -> str:
    return address.split(":", 1)[1].removeprefix("!")


def test_every_solver_is_a_class_its_environment_provides() -> None:
    environments = {e.name for e in load_environments().environments}
    solvers = load_solvers().solvers
    assert {s.id for s in solvers} >= {"copasi", "tellurium"}
    for s in solvers:
        assert s.environment in environments, f"{s.id}: no environment {s.environment!r}"
        manifest = _manifest(s.environment)
        assert manifest is not None, f"{s.id}: {s.environment} has no manifest"
        found = next((c for c in manifest.components if _key(c.address) == _key(s.address)), None)
        assert found is not None, f"{s.id}: {s.address} is not in {s.environment}'s manifest"
        assert found.registry_entry is not None and found.registry_entry.level in ("tested", "validated", "curated")
        # the role's face (process-bigraph-lang's TimeCourseSolver): what `sedml translate` writes and wires
        assert set(found.config_schema) >= {"model_source", "time", "n_points", "output_dir"}
        assert set(found.outputs or {}) == {"result"}
        assert all(a.startswith("KISAO:") for a in s.algorithms)


def test_the_translation_form() -> None:
    copasi = solver("copasi")
    assert copasi is not None
    assert copasi.as_translation_data() == {
        "id": "copasi",
        "address": "local:pbsim_common.simulators.copasi_process.CopasiUTCStep",
        "algorithms": ["KISAO:0000560", "KISAO:0000088"],
        "provides": ["species"],
    }
    assert solver("nope") is None


@pytest.mark.asyncio
async def test_route_lists_the_solvers() -> None:
    app = FastAPI()
    app.include_router(registry_router.config.router, prefix=registry_router.config.prefix)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        listing = (await c.get("/registry/solvers")).json()
    assert [s["id"] for s in listing] == ["copasi", "tellurium", "vcell"]
    assert listing[1]["algorithms"] == ["KISAO:0000019"] and listing[1]["environment"] == "registry_env"
