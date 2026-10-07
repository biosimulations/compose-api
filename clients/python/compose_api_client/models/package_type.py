from enum import StrEnum


class PackageType(StrEnum):
    CONDA = "conda"
    PYPI = "pypi"

    def __str__(self) -> str:
        return str(self.value)
