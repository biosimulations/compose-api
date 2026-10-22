from enum import StrEnum


class ImageState(StrEnum):
    AVAILABLE = "available"
    BUILDING = "building"
    FAILED = "failed"
    MISSING = "missing"

    def __str__(self) -> str:
        return str(self.value)
