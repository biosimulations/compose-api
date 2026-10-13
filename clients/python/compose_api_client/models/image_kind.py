from enum import StrEnum


class ImageKind(StrEnum):
    OCI = "oci"
    SIF = "sif"

    def __str__(self) -> str:
        return str(self.value)
