"""Shared by the SED-ML route tests: runs recorded instead of submitted, a client, and the translator's presence."""

import itertools
import json
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from compose_api.api.main import app
from compose_api.config import get_settings, override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.sedml import service, sources
from compose_api.simulation.hpc_utils import get_singularity_hash
from compose_api.simulation.models import SimulationExperiment, SimulationRequest
from compose_api.simulation.prebuilt import prebuilt_definition

RESOURCES = Path(__file__).resolve().parents[1] / "fixtures" / "resources"
RECORDED = RESOURCES / "sources"
PROJECT = "Morphogenesis-checkpoint-continuous-Ciliberto-J-Cell-Biol-2003"

needs_translator = pytest.mark.skipif(
    not Path(get_settings().pblang_python).exists(), reason="process-bigraph-lang is not installed (make pblang)"
)

_ids = itertools.count(1)


@pytest_asyncio.fixture
async def submitted(
    database_service: DatabaseServiceSQL, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[dict[str, Any]]:
    """Runs recorded, not submitted: each request, its simulation id and its experiment id."""
    sim_db = database_service.get_simulator_db()
    definition = prebuilt_definition("ghcr.io/example/registry_env@sha256:" + "1" * 64)
    simulator = await sim_db.get_simulator_by_def_hash(get_singularity_hash(definition))
    simulator = simulator or await sim_db.insert_simulator(definition, packages_used=None)
    recorded: dict[str, Any] = {"runs": []}

    async def run_simulation(simulation_request: SimulationRequest, **_: object) -> SimulationExperiment:
        experiment_id = f"exp-sedml-{next(_ids)}-{tmp_path.name}"
        sim = await sim_db.insert_simulation(simulation_request, experiment_id, simulator)
        recorded["runs"].append((simulation_request, sim.database_id, experiment_id))
        return SimulationExperiment(simulation_database_id=sim.database_id, simulator_database_id=simulator.database_id)

    monkeypatch.setattr(service, "run_simulation", run_simulation)
    monkeypatch.setattr(service, "get_required_simulation_service", lambda: None)
    monkeypatch.setattr(service, "get_required_job_monitor", lambda: None)
    with override_settings(internal_mount_dir=str(tmp_path / "mount")):
        yield recorded


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=120) as c:
        yield c


@pytest.fixture
def recorded_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[list[str]]:
    """Upstream answered from fixtures; every URL asked is listed."""
    asked: list[str] = []
    run = json.loads((RECORDED / "ciliberto_project.json").read_text())["simulationRun"]
    # BIOMD0000000012's COPASI project on biosimulations.org, imported from BioModels (docs/plan-verify-oracle.md, V1)
    legacy = json.loads((RECORDED / "legacy_BIOMD12_project.json").read_text())
    answers: dict[str, Any] = {
        f"{sources.BIOMODELS}/search": json.loads((RECORDED / "biomodels_search.json").read_text()),
        f"{sources.BIOMODELS}/BIOMD0000000012": json.loads((RECORDED / "BIOMD0000000012.json").read_text()),
        f"{sources.BIOMODELS}/model/download/BIOMD0000000012": (RECORDED / "BIOMD0000000012.omex").read_bytes(),
        f"{sources.BIOSIMULATIONS}/projects": [json.loads((RECORDED / "ciliberto_project.json").read_text()), legacy],
        f"{sources.BIOSIMULATIONS}/projects/{legacy['id']}": legacy,
        f"{sources.BIOSIMULATIONS}/runs/{legacy['simulationRun']}": json.loads(
            (RECORDED / "legacy_BIOMD12_run.json").read_text()
        ),
        f"{sources.BIOSIMULATIONS}/results/{legacy['simulationRun']}/download": (
            RECORDED / "legacy_BIOMD12_results.zip"
        ).read_bytes(),
        f"{sources.BIOSIMULATIONS}/projects/{PROJECT}": json.loads((RECORDED / "ciliberto_project.json").read_text()),
        f"{sources.BIOSIMULATIONS}/runs/{run}": json.loads((RECORDED / "ciliberto_run.json").read_text()),
        f"{sources.BIOSIMULATIONS}/runs/{run}/download": (
            RESOURCES / "sedml" / "Ciliberto2003.source.omex"
        ).read_bytes(),
        f"{sources.BIOSIMULATIONS}/results/{run}/download": (RECORDED / "ciliberto_results.zip").read_bytes(),
    }

    async def get(url: str, *, json: bool = True, params: dict[str, Any] | None = None) -> Any:
        asked.append(url)
        if url not in answers:
            raise sources.SourceNotFoundError(url)
        return answers[url]

    monkeypatch.setattr(sources, "_get", get)
    monkeypatch.setattr(sources, "_memo", {})
    with override_settings(sources_cache_dir=str(tmp_path / "cache")):
        yield asked
