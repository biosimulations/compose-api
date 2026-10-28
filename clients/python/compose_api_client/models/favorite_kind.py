from enum import StrEnum


class FavoriteKind(StrEnum):
    COMPARISON = "comparison"
    SIMULATION = "simulation"
    SUITE_RUN = "suite_run"

    def __str__(self) -> str:
        return str(self.value)
