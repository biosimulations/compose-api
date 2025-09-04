from dataclasses import dataclass
from enum import Enum


class ContainerizationTypes(Enum):
    NONE=0
    SINGLE=1
    MULTIPLE=2


class ContainerizationEngine(Enum):
    NONE=0
    DOCKER=1
    APPTAINER=2
    BOTH=3


@dataclass
class ProgramArguments:
    input_file_path: str
    output_dir: str | None
    whitelist_entries: list[str]
    containerization_type: ContainerizationTypes
    containerization_engine: ContainerizationEngine
