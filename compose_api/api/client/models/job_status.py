from enum import Enum


class JobStatus(str, Enum):
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    OUT_OF_MEMORY = "out_of_memory"
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUSPENDED = "suspended"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    WAITING = "waiting"

    def __str__(self) -> str:
        return str(self.value)
