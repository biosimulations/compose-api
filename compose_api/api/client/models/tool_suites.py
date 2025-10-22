from enum import Enum


class ToolSuites(str, Enum):
    BASICO = "basico"
    TELLURIUM = "tellurium"

    def __str__(self) -> str:
        return str(self.value)
