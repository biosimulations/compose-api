"""The library list pbest's shared image was made from, kept for the tests (docs/plan-environment-composition.md, 8d).

The service made registry_env's image from it until its versions were composed (registry_env@1 is that image; @5,
composed with pixi, is the default since 2026-10-26). The test database's registry_env default still runs pbest's
definition of it, which the SLURM tests build and run (tests/fixtures/postgres_fixtures.seed_shared_default). A copy
of biosimulations/registry's registry.json at `REGISTRY_SOURCE` (that repository is archived).
"""

import json
from pathlib import Path

from pbest.utils.input_types import DependencyTypes, ExperimentDependency, ExperimentPrimaryDependencies
from pydantic import HttpUrl

REGISTRY_SOURCE = (
    "https://github.com/biosimulations/registry/blob/f8b013277230da8561e739f409d6f15619fa85dc/registry.json"
)
_REGISTRY_PATH = Path(__file__).parent / "resources" / "simulator_registry.json"


def registry_libraries() -> list[dict[str, str]]:
    """The pinned library list, as recorded in a shared environment version's spec."""
    libraries: list[dict[str, str]] = json.loads(_REGISTRY_PATH.read_text())["libraries"]
    return libraries


def registry_dependencies() -> ExperimentPrimaryDependencies:
    """Parse the pinned registry the same way pbest's `_default_registry_deps` parses the fetched one."""
    libraries = registry_libraries()
    pypi: list[ExperimentDependency] = []
    conda: list[ExperimentDependency] = []
    for lib in libraries:
        is_pypi = lib["package_registry"] == "pypi"
        dep = ExperimentDependency(
            dependency_name=lib["name"],
            url_reference=HttpUrl(lib["url"]),
            dependency_type=DependencyTypes.PYPI if is_pypi else DependencyTypes.CONDA,
            version=lib.get("version", ""),
        )
        (pypi if is_pypi else conda).append(dep)
    return ExperimentPrimaryDependencies(pypi_dependencies=pypi, conda_dependencies=conda)
