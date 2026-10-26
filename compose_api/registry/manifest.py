"""The simulator registry manifest: the components this service will run, and how far each has been checked.

The manifest is a versioned file in this package, reviewed by pull request, and read at call time. It is the
registry of record described by strategy decision 5; the database tables that predate it are not consulted.
"""

import enum
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

_MANIFEST_PATH = Path(__file__).parent / "manifest.yaml"
# Generated from the vivarium-collective catalog by `python -m compose_api.registry.catalog`: every wrapper, at
# level `listed`. An entry in manifest.yaml takes precedence over one here with the same id.
CATALOG_PATH = Path(__file__).parent / "catalog.yaml"

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


_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class Install(BaseModel):
    """How an entry is installed into a composed environment (docs/plan-environment-composition.md, C2): a release
    from PyPI, or a git repository at a full commit, with any extras."""

    pypi: str | None = None
    version: str | None = None
    git: str | None = None
    commit: str | None = None
    extras: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_source_pinned(self) -> "Install":
        if (self.pypi is None) == (self.git is None):
            raise ValueError("an install names exactly one of `pypi` and `git`")
        if self.pypi is not None and not self.version:
            raise ValueError(f"`pypi: {self.pypi}` needs its exact `version`")
        if self.git is not None and not (self.commit and _COMMIT.match(self.commit)):
            raise ValueError(f"`git: {self.git}` needs a full 40-character `commit`, never a branch")
        return self

    @property
    def name(self) -> str:
        """The distribution's name, normalized, from PyPI's name or the repository's."""
        raw = self.pypi or (self.git or "").rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
        return re.sub(r"[-_.]+", "-", raw).lower()


class RegistryEntry(BaseModel):
    id: str
    package: str
    source: str
    # a `component` provides process classes (its module roots) and is what admission and compliance are about; a
    # `library` is installed for a component's sake (an engine, or a pin on a component's floating dependency)
    kind: Literal["component", "library"] = "component"
    version: str | None = None
    commit: str | None = None
    module_roots: list[str] = Field(default_factory=list)
    level: CurationLevel
    bundles: list[str] = Field(default_factory=list)
    install: Install | None = None
    # conda-forge requirements, name -> version spec, for what PyPI cannot supply (MPI, PETSc, a C++ engine)
    conda: dict[str, str] = Field(default_factory=dict)
    # type tables the runner registers before a run, `module:attribute` (pbsim_common:standard_types)
    types: list[str] = Field(default_factory=list)
    # the library entries a component needs installed beside it (an engine its package does not declare), which join
    # the entries a document is inferred to need (docs/plan-environment-composition.md, D7.2)
    requires: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    reviewer: str | None = None

    @model_validator(mode="after")
    def _pinned(self) -> "RegistryEntry":
        if self.version is None and self.commit is None:
            raise ValueError(f"registry entry {self.id!r} must be pinned by version or commit")
        if self.kind == "component" and not self.module_roots:
            raise ValueError(f"registry entry {self.id!r} is a component, so it needs `module_roots`")
        return self


class Manifest(BaseModel):
    entries: list[RegistryEntry]

    @model_validator(mode="after")
    def _unique_ids(self) -> "Manifest":
        ids = [entry.id for entry in self.entries]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate registry entry ids: {duplicates}")
        unknown = sorted({r for e in self.entries for r in e.requires if r not in ids})
        if unknown:
            raise ValueError(f"`requires` names entries the manifest does not have: {unknown}")
        return self

    def with_requirements(self, entry_ids: set[str]) -> set[str]:
        """The entries, and every entry they require, transitively."""
        by_id = {entry.id: entry for entry in self.entries}
        found, pending = set(), list(entry_ids)
        while pending:
            entry_id = pending.pop()
            if entry_id in found:
                continue
            found.add(entry_id)
            entry = by_id.get(entry_id)
            pending.extend(entry.requires if entry is not None else [])
        return found

    def entry_for_module(self, module: str) -> RegistryEntry | None:
        """The entry whose longest module root contains `module`, so a nested root wins over its parent."""
        best: tuple[int, RegistryEntry] | None = None
        for entry in self.entries:
            for root in entry.module_roots:
                if (module == root or module.startswith(root + ".")) and (best is None or len(root) > best[0]):
                    best = (len(root), entry)
        return None if best is None else best[1]


def load_manifest(path: Path = _MANIFEST_PATH, catalog_path: Path | None = CATALOG_PATH) -> Manifest:
    """The curated manifest, plus every catalog entry it does not already name."""
    curated = Manifest.model_validate(yaml.safe_load(path.read_text()))
    if catalog_path is None or not catalog_path.exists():
        return curated
    named = {entry.id for entry in curated.entries}
    catalog = Manifest.model_validate(yaml.safe_load(catalog_path.read_text()) or {"entries": []})
    return Manifest(entries=[*curated.entries, *(e for e in catalog.entries if e.id not in named)])
