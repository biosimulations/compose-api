from dataclasses import dataclass
from enum import Enum


class ContainerizationTypes(Enum):
    NONE = 0
    SINGLE = 1
    MULTIPLE = 2


class ContainerizationEngine(Enum):
    NONE = 0
    DOCKER = 1
    APPTAINER = 2
    BOTH = 3


class ContainerizationFileRepr:
    def __init__(self, representation: str):
        self.representation = representation


class ExperimentPrimaryDependencies:
    _pypi_dependencies: list[str]
    _conda_dependencies: list[str]
    _compact_repr: str

    def __init__(self, pypi_dependencies: list[str], conda_dependencies: list[str]) -> None:
        self._pypi_dependencies = pypi_dependencies
        self._conda_dependencies = conda_dependencies
        self._compact_repr = ",".join(pypi_dependencies) + ";" + ",".join(conda_dependencies)

    def __str__(self) -> str:
        pypi_dependencies: str = "PyPi Dependencies:\n\t" + "\n\t".join(self._pypi_dependencies)
        conda_dependencies: str = "Conda Dependencies:\n\t" + "\n\t".join(self._conda_dependencies)
        return pypi_dependencies + "\n" + ("-" * 25) + "\n" + conda_dependencies

    def __repr__(self) -> str:
        pypi_dependencies: str = "pypi:" + ",pypi:".join(self._pypi_dependencies)
        conda_dependencies: str = "conda:" + ",conda:".join(self._conda_dependencies)
        return pypi_dependencies + "," + conda_dependencies

    def get_compact_repr(self) -> str:
        return self._compact_repr

    def get_pypi_dependencies(self) -> list[str]:
        return self._pypi_dependencies

    def get_conda_dependencies(self) -> list[str]:
        return self._conda_dependencies


@dataclass
class ProgramArguments:
    input_file_path: str
    output_dir: str | None
    passlist_entries: list[str]
    containerization_type: ContainerizationTypes
    containerization_engine: ContainerizationEngine
