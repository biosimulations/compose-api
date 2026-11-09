from enum import StrEnum


class SuiteJudgedBy(StrEnum):
    AGREEMENT = "agreement"
    REFERENCE = "reference"

    def __str__(self) -> str:
        return str(self.value)
