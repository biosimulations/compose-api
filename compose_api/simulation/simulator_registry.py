"""The libraries installed into the shared simulator image.

The list used to be fetched on every simulation request from the `dev` branch of `biosimulations/registry`, so any
commit there silently changed the generated container definition, and with it the md5 that identifies a
`SimulatorVersion`, and triggered a rebuild. It is now a copy of that file pinned at `REGISTRY_SOURCE`, so the
identity changes only when this file does, in a reviewed commit. To take an upstream change, copy the new file here
and update `REGISTRY_SOURCE`; expect a container rebuild on the next run.
"""

import json
from pathlib import Path

from pbest.utils.input_types import DependencyTypes, ExperimentDependency, ExperimentPrimaryDependencies
from pydantic import HttpUrl

REGISTRY_SOURCE = (
    "https://github.com/biosimulations/registry/blob/f8b013277230da8561e739f409d6f15619fa85dc/registry.json"
)
_REGISTRY_PATH = Path(__file__).parent / "simulator_registry.json"


def registry_dependencies() -> ExperimentPrimaryDependencies:
    """Parse the pinned registry the same way pbest's `_default_registry_deps` parses the fetched one."""
    libraries = json.loads(_REGISTRY_PATH.read_text())["libraries"]
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
