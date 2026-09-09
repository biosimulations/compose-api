from enum import StrEnum


class JobType(StrEnum):
    BUILD_CONTAINER = "build_container"
    SIMULATION = "simulation"

    def __str__(self) -> str:
        return str(self.value)
