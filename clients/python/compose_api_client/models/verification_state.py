from enum import StrEnum


class VerificationState(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    REQUESTED = "requested"
    SUBMITTED = "submitted"

    def __str__(self) -> str:
        return str(self.value)
