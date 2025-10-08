from enum import Enum


class PackageType(str, Enum):
    CONDA = "conda"
    PYTHON = "python"

    def __str__(self) -> str:
        return str(self.value)
