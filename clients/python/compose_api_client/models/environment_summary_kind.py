from enum import StrEnum


class EnvironmentSummaryKind(StrEnum):
    PREBUILT = "prebuilt"
    SHARED = "shared"

    def __str__(self) -> str:
        return str(self.value)
