from enum import StrEnum


class SubmissionState(StrEnum):
    FAILED = "failed"
    PREPARING = "preparing"
    REQUESTED = "requested"
    SUBMITTED = "submitted"
    SUBMITTING = "submitting"

    def __str__(self) -> str:
        return str(self.value)
