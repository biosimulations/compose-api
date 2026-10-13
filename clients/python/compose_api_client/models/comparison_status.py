from enum import StrEnum


class ComparisonStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    RUNNING = "running"

    def __str__(self) -> str:
        return str(self.value)
