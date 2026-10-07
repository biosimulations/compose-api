from enum import StrEnum


class ListSimulationsStatusType0(StrEnum):
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    OUT_OF_MEMORY = "out_of_memory"
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUBMITTING = "submitting"
    SUSPENDED = "suspended"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    WAITING = "waiting"

    def __str__(self) -> str:
        return str(self.value)
