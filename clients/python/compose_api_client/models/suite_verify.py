from enum import StrEnum


class SuiteVerify(StrEnum):
    ALL = "all"
    FAILING = "failing"
    NONE = "none"

    def __str__(self) -> str:
        return str(self.value)
