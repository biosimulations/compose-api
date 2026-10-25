from enum import StrEnum


class LockPreviewAgainstBasisType0(StrEnum):
    INSTALLED = "installed"
    LOCK = "lock"

    def __str__(self) -> str:
        return str(self.value)
