"""The simulator registry manifest: the components this service will run, and how far each has been checked.

The manifest is a versioned file in this package, reviewed by pull request, and read at call time. It is the
registry of record described by strategy decision 5; the database tables that predate it are not consulted.
"""

import enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

_MANIFEST_PATH = Path(__file__).parent / "manifest.yaml"

# The bundle the service currently runs every composite in. See strategy decision 5, "registry_env is the first
# bundle, and a stopgap".
SERVICE_BUNDLE = "registry_env"


class CurationLevel(enum.StrEnum):
    """The curation ladder, lowest first. Order matters: comparisons use the declaration order."""

    LISTED = "listed"
    INSTALLABLE = "installable"
    TESTED = "tested"
    VALIDATED = "validated"
    CURATED = "curated"

    @property
    def rank(self) -> int:
        return list(CurationLevel).index(self)

    def at_least(self, other: "CurationLevel") -> bool:
        return self.rank >= other.rank


# The lowest level the service will run on HPC (goal G6).
HPC_MINIMUM_LEVEL = CurationLevel.TESTED


class RegistryEntry(BaseModel):
    id: str
    package: str
    source: str
    version: str | None = None
    commit: str | None = None
    module_roots: list[str] = Field(min_length=1)
    level: CurationLevel
    bundles: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    reviewer: str | None = None

    @model_validator(mode="after")
    def _pinned(self) -> "RegistryEntry":
        if self.version is None and self.commit is None:
            raise ValueError(f"registry entry {self.id!r} must be pinned by version or commit")
        return self


class Manifest(BaseModel):
    entries: list[RegistryEntry]

    @model_validator(mode="after")
    def _unique_ids(self) -> "Manifest":
        ids = [entry.id for entry in self.entries]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate registry entry ids: {duplicates}")
        return self

    def entry_for_module(self, module: str) -> RegistryEntry | None:
        """The entry whose longest module root contains `module`, so a nested root wins over its parent."""
        best: tuple[int, RegistryEntry] | None = None
        for entry in self.entries:
            for root in entry.module_roots:
                if (module == root or module.startswith(root + ".")) and (best is None or len(root) > best[0]):
                    best = (len(root), entry)
        return None if best is None else best[1]


def load_manifest(path: Path = _MANIFEST_PATH) -> Manifest:
    return Manifest.model_validate(yaml.safe_load(path.read_text()))
