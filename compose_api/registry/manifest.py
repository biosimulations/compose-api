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
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
# a wheel by https URL, with nothing a definition's shell line or a TOML string would have to escape
_WHEEL_URL = re.compile(r"^https://[^\s'\"#?]+/(?P<file>[^/\s'\"#?]+\.whl)$")


class Install(BaseModel):
    """How an entry is installed into a composed environment (docs/plan-environment-composition.md, C2): a release
    from PyPI, a git repository at a full commit, or a wheel by URL and its sha256 (7c-2: one no index publishes, such
    as Smoldyn built for VCell), with any extras."""

    pypi: str | None = None
    version: str | None = None
    git: str | None = None
    commit: str | None = None
    url: str | None = None
    sha256: str | None = None
    extras: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_source_pinned(self) -> "Install":
        if [self.pypi, self.git, self.url].count(None) != 2:
            raise ValueError("an install names exactly one of `pypi`, `git` and `url`")
        if self.url is not None:
            if not _WHEEL_URL.match(self.url):
                raise ValueError(f"`url: {self.url}` must be an https URL of a `.whl`, with no query or fragment")
            if not (self.sha256 and _SHA256.match(self.sha256)):
                raise ValueError(f"`url: {self.url}` needs the wheel's `sha256`: pixi checks no hash of its own")
        elif self.sha256 is not None:
            raise ValueError("`sha256` is for a `url` install")
        if self.pypi is not None and not self.version:
            raise ValueError(f"`pypi: {self.pypi}` needs its exact `version`")
        if self.git is not None and not (self.commit and _COMMIT.match(self.commit)):
            raise ValueError(f"`git: {self.git}` needs a full 40-character `commit`, never a branch")
        return self

    @property
    def name(self) -> str:
        """The distribution's name, normalized, from PyPI's name, the repository's, or the wheel's file name."""
        if self.url is not None:
            match = _WHEEL_URL.match(self.url)
            raw = match.group("file").split("-", 1)[0] if match else self.url
        else:
            raw = self.pypi or (self.git or "").rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
        return re.sub(r"[-_.]+", "-", raw).lower()


class RegistryEntry(BaseModel):
    id: str
    package: str
    source: str
    # a `component` provides process classes (its module roots) and is what admission and compliance are about; a
    # `library` is installed for a component's sake (an engine, or a pin on a component's floating dependency); a
    # `core` entry is classes of the engine every composed environment installs (`composition.core` in
    # environments.yaml), so it is provided by every composed version and mash-up without being listed or installed,
    # and by the prebuilt images its `bundles` name (docs/plan-environment-composition.md, 7c-1)
    kind: Literal["component", "library", "core"] = "component"
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
    # whose commit an environment administrator may move by making a version, without a pull request
    # (docs/plan-entry-updates.md, E2): any commit on the repository's default branch (`main`), or only one a release
    # tag points at (`tags`). Only a git install can move; its compliance cases are what certify the new commit
    updates: Literal["main", "tags"] | None = None

    @model_validator(mode="after")
    def _pinned(self) -> "RegistryEntry":
        if self.version is None and self.commit is None:
            raise ValueError(f"registry entry {self.id!r} must be pinned by version or commit")
        if self.kind in ("component", "core") and not self.module_roots:
            raise ValueError(f"registry entry {self.id!r} is a {self.kind}, so it needs `module_roots`")
        if self.kind == "core" and (self.install is not None or self.conda):
            raise ValueError(f"registry entry {self.id!r} is core: the composition installs it, so it has no install")
        if self.updates is not None and (self.install is None or self.install.git is None):
            raise ValueError(f"registry entry {self.id!r} has `updates`, which only a `git` install can follow")
        return self

    def at_commit(self, commit: str) -> "RegistryEntry":
        """This entry moved to ``commit`` (docs/plan-entry-updates.md): its pin and its install's, nothing else."""
        if self.install is None or self.install.git is None:
            raise ValueError(f"registry entry {self.id!r} is not a git install, so it has no commit to move")
        return self.model_copy(update={"commit": commit, "install": self.install.model_copy(update={"commit": commit})})


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

    def core_entries(self) -> list[RegistryEntry]:
        """The entries every composed environment provides through its core."""
        return [entry for entry in self.entries if entry.kind == "core"]

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
