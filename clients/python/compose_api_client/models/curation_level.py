from enum import StrEnum


class CurationLevel(StrEnum):
    CURATED = "curated"
    INSTALLABLE = "installable"
    LISTED = "listed"
    TESTED = "tested"
    VALIDATED = "validated"

    def __str__(self) -> str:
        return str(self.value)
