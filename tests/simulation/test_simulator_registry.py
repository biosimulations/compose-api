import httpx
import pytest
from pbest.containerization.container_constructor import generate_container_def_file
from pbest.utils.input_types import ContainerizationEngine

from compose_api.simulation.hpc_utils import get_singularity_hash
from compose_api.simulation.simulator_registry import registry_dependencies


def test_pinned_registry_parses_into_pypi_and_conda() -> None:
    deps = registry_dependencies()
    assert [d.dependency_name for d in deps.pypi_dependencies] == ["python-copasi", "tellurium", "pb_multiscale_actin"]
    assert [d.dependency_name for d in deps.conda_dependencies] == ["readdy"]
    assert all(d.version for d in deps.pypi_dependencies + deps.conda_dependencies)


def test_simulator_identity_needs_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The definition, and so the SimulatorVersion hash, must not depend on fetching anything at request time."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("simulator identity must not fetch over the network")

    monkeypatch.setattr(httpx, "get", refuse)
    first = generate_container_def_file(registry_dependencies(), ContainerizationEngine.APPTAINER)
    second = generate_container_def_file(registry_dependencies(), ContainerizationEngine.APPTAINER)
    assert get_singularity_hash(first) == get_singularity_hash(second)
