from enum import StrEnum


class VersionState(StrEnum):
    BUILDING = "building"
    FAILED = "failed"
    READY = "ready"
    RESOLVING = "resolving"
    RETIRED = "retired"

    def __str__(self) -> str:
        return str(self.value)
