from enum import Enum


class JobType(str, Enum):
    SIMULATION = "simulation"

    def __str__(self) -> str:
        return str(self.value)
