from enum import StrEnum


class BiGraphComputeType(StrEnum):
    PROCESS = "process"
    STEP = "step"

    def __str__(self) -> str:
        return str(self.value)
