from enum import StrEnum


class VerifySuiteRunWhich(StrEnum):
    ALL = "all"
    FAILING = "failing"

    def __str__(self) -> str:
        return str(self.value)
