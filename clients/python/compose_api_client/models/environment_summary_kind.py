from enum import StrEnum


class EnvironmentSummaryKind(StrEnum):
    MASH_UP = "mash-up"
    PREBUILT = "prebuilt"
    SHARED = "shared"

    def __str__(self) -> str:
        return str(self.value)
