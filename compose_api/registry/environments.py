"""The environments documents run in, and the interface manifests CI reads from each one.

A manifest (`manifests/<name>.json`, format `pbg-interfaces/1`, shared with process-bigraph-lang and other tools)
lists the step and process classes an environment provides, with their config schemas and ports, as read inside its
image. `environments.yaml` says which environments there are and how to enter each one's Python; which modules are
read comes from the registry entries whose `bundles` name the environment. The API serves the manifests to the web
app's editor and checker (`/registry/environments`).
"""

import functools
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from compose_api.config import get_settings
from compose_api.registry.manifest import CurationLevel, Manifest, RegistryEntry, load_manifest

ENVIRONMENTS_PATH = Path(__file__).parent / "environments.yaml"
MANIFESTS_DIR = Path(__file__).parent / "manifests"
INTERFACES_VERSION = "pbg-interfaces/1"


class DescribeSource(BaseModel):
    source: str
    ref: str
    path: str

    @property
    def raw_url(self) -> str:
        repo = self.source.removeprefix("https://github.com/").removesuffix(".git")
        return f"https://raw.githubusercontent.com/{repo}/{self.ref}/{self.path}"


class EnvironmentSpec(BaseModel):
    name: str
    kind: Literal["shared", "prebuilt"]
    python: list[str] = Field(min_length=1)
    # the registry entries composed into it (docs/plan-environment-composition.md, C2): each declares how it installs.
    # A prebuilt image's contents are its owner's, so it lists none.
    entries: list[str] = Field(default_factory=list)
    python_version: str | None = None


class Composition(BaseModel):
    """How composed environments are built: the pixi image that locks and builds them, the platform they are locked
    for, and the common core every one of them pins (EV3)."""

    pixi_image: str
    platform: str = "linux-64"
    core: dict[str, str] = Field(default_factory=dict)


class EnvironmentsFile(BaseModel):
    describe: DescribeSource
    composition: Composition | None = None
    environments: list[EnvironmentSpec]


def composition_problems(environments: EnvironmentsFile, manifest: Manifest) -> list[str]:
    """What keeps each environment's `entries` from being composed: an entry that is unknown or has no `install`, two
    entries installing one distribution, and a disagreement with the entries' own `bundles` (both say where an entry is
    installed until `bundles` is retired). Empty when every composition is sound."""
    return [p for spec in environments.environments if spec.entries for p in spec_problems(spec, manifest)]


def spec_problems(spec: EnvironmentSpec, manifest: Manifest, *, bundled: bool = True) -> list[str]:
    """What keeps one environment's `entries` from being composed (`composition_problems`); without ``bundled``, a
    mash-up's: its entries are not bundled in the environment it is a version of."""
    by_id = {e.id: e for e in manifest.entries}
    problems: list[str] = []
    if spec.kind == "prebuilt":
        problems.append(f"{spec.name}: a prebuilt image is its owner's, so it lists no entries")
    if len(set(spec.entries)) != len(spec.entries):
        problems.append(f"{spec.name}: an entry is listed twice")
    installs: dict[str, str] = {}
    for entry_id in spec.entries:
        entry = by_id.get(entry_id)
        if entry is None:
            problems.append(f"{spec.name}: no registry entry {entry_id!r}")
        elif entry.install is None and not entry.conda:
            problems.append(f"{spec.name}: entry {entry_id!r} does not say how it installs (`install` or `conda`)")
        else:
            names = [entry.install.name] if entry.install is not None else []
            for name in [*names, *(f"conda:{c}" for c in entry.conda)]:
                other = installs.setdefault(name, entry_id)
                if other != entry_id:
                    problems.append(f"{spec.name}: {other!r} and {entry_id!r} both install {name}")
    problems.extend(_unlisted_requirements(spec, by_id))
    in_bundle = {e.id for e in manifest.entries if spec.name in e.bundles}
    if bundled and in_bundle != set(spec.entries):
        problems.append(
            f"{spec.name}: its entries {sorted(set(spec.entries))} differ from the entries bundled in it"
            f" {sorted(in_bundle)}"
        )
    return problems


def members_of(spec: EnvironmentSpec, manifest: Manifest) -> frozenset[str]:
    """The registry entries an environment provides: those it is composed of, or, for a prebuilt image (which lists
    none), the entries bundled in it."""
    return frozenset(spec.entries) or frozenset(e.id for e in manifest.entries if spec.name in e.bundles)


def _unlisted_requirements(spec: EnvironmentSpec, by_id: dict[str, RegistryEntry]) -> list[str]:
    """An entry the environment lists that `requires` one it does not (D7.2: what a component needs comes with it)."""
    problems = []
    for entry_id in spec.entries:
        entry = by_id.get(entry_id)
        missing = sorted(set(entry.requires) - set(spec.entries)) if entry is not None else []
        if missing:
            problems.append(f"{spec.name}: entry {entry_id!r} requires {missing}, which it does not list")
    return problems


def load_environments(path: Path = ENVIRONMENTS_PATH) -> EnvironmentsFile:
    return EnvironmentsFile.model_validate(yaml.safe_load(path.read_text()))


def module_roots(environment: str, manifest: Manifest | None = None) -> list[str]:
    """The module roots of every registry entry in the environment's bundle."""
    manifest = manifest or load_manifest()
    return sorted({root for e in manifest.entries if environment in e.bundles for root in e.module_roots})


@functools.cache
def shared_image() -> str:
    """The shared image's reference: the repository plus the hash of the definition the service generates."""
    from pbest.containerization.container_constructor import generate_container_def_file
    from pbest.utils.input_types import ContainerizationEngine

    from compose_api.simulation.hpc_utils import get_singularity_hash
    from compose_api.simulation.simulator_registry import registry_dependencies

    definition = generate_container_def_file(registry_dependencies(), ContainerizationEngine.APPTAINER)
    return f"{get_settings().simulator_image_repository}:{get_singularity_hash(definition)}"


def deployed_image(spec: EnvironmentSpec, prebuilt: dict[str, str] | None = None) -> str | None:
    """The image this deployment runs the environment in; None for a prebuilt one it does not list."""
    if spec.kind == "shared":
        return shared_image()
    pins = get_settings().prebuilt_simulators if prebuilt is None else prebuilt
    return pins.get(spec.name)


# --- the served form --------------------------------------------------------------------------------------------


class EntryRef(BaseModel):
    """The registry entry a component belongs to (by module root), and its curation level."""

    id: str
    level: CurationLevel


class InterfaceComponent(BaseModel):
    """One step or process class, as `pbg-interfaces/1` describes it; unknown keys pass through."""

    model_config = ConfigDict(extra="allow")

    name: str
    kind: str
    address: str
    module: str | None = None
    description: str | None = None
    config_schema: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    dynamic_ports: bool = False
    registry_entry: EntryRef | None = None


class InterfaceManifest(BaseModel):
    """An environment's interface manifest (`pbg-interfaces/1`), with each component's registry entry added."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_: str | None = Field(default=None, alias="$schema")
    schema_version: str
    environment: dict[str, Any] | None = None
    components: list[InterfaceComponent]
    errors: list[dict[str, str]] = Field(default_factory=list)


class EnvironmentSummary(BaseModel):
    name: str
    kind: Literal["shared", "prebuilt"]
    simulator: str | None = Field(description="The value of /simulation/run's `simulator` for this environment")
    image: str | None = Field(description="The image this deployment runs it in")
    manifest_image: str | None = Field(description="The image the manifest was read from")
    stale: bool = Field(description="The manifest was read from another image than the one deployed")
    process_bigraph: str | None = None
    components: int
    errors: int
    entries: list[EntryRef]


def manifest_path(name: str) -> Path:
    return MANIFESTS_DIR / f"{name}.json"


def read_manifest(name: str, registry: Manifest | None = None) -> InterfaceManifest | None:
    """An environment's manifest with each component's registry entry, or None when none has been generated."""
    path = manifest_path(name)
    if not path.exists():
        return None
    manifest = InterfaceManifest.model_validate(json.loads(path.read_text()))
    registry = registry or load_manifest()
    for component in manifest.components:
        entry = registry.entry_for_module(component.module or component.address.split("!", 1)[-1])
        component.registry_entry = None if entry is None else EntryRef(id=entry.id, level=entry.level)
    return manifest


def summarize(spec: EnvironmentSpec, prebuilt: dict[str, str] | None = None) -> EnvironmentSummary | None:
    """The environment as the web app lists it; None for a prebuilt one this deployment does not offer."""
    image = deployed_image(spec, prebuilt)
    if image is None:
        return None
    registry = load_manifest()
    manifest = read_manifest(spec.name, registry)
    recorded = (manifest.environment or {}).get("image") if manifest else None
    entries = [EntryRef(id=e.id, level=e.level) for e in registry.entries if spec.name in e.bundles]
    return EnvironmentSummary(
        name=spec.name,
        kind=spec.kind,
        simulator=spec.name if spec.kind == "prebuilt" else None,
        image=image,
        manifest_image=recorded,
        stale=manifest is not None and recorded != image,
        process_bigraph=(manifest.environment or {}).get("process_bigraph") if manifest else None,
        components=len(manifest.components) if manifest else 0,
        errors=len(manifest.errors) if manifest else 0,
        entries=entries,
    )


class EntryEnvironment(BaseModel):
    """An environment that provides some of a registry entry's classes, and how many."""

    name: str
    components: int


class CatalogEntry(BaseModel):
    """A registry entry as the catalog shows it (docs/plan-sedml.md, "Concepts"): what it is, how far it is trusted,
    and which of this deployment's environments provide its classes. Most `listed` entries are in none."""

    id: str
    package: str
    source: str
    version: str | None = None
    commit: str | None = None
    level: CurationLevel
    module_roots: list[str]
    bundles: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    reviewer: str | None = None
    environments: list[EntryEnvironment] = Field(default_factory=list)


def catalog_entries(prebuilt: dict[str, str] | None = None) -> list[CatalogEntry]:
    """Every registry entry (manifest.yaml over catalog.yaml), highest level first, then by id, each with the offered
    environments whose manifest lists its classes."""
    registry = load_manifest()
    provided: dict[str, list[EntryEnvironment]] = {}
    for spec in load_environments().environments:
        if deployed_image(spec, prebuilt) is None:
            continue
        manifest = read_manifest(spec.name, registry)
        counts: dict[str, int] = {}
        for component in manifest.components if manifest else []:
            if component.registry_entry is not None:
                counts[component.registry_entry.id] = counts.get(component.registry_entry.id, 0) + 1
        for entry_id, n in counts.items():
            provided.setdefault(entry_id, []).append(EntryEnvironment(name=spec.name, components=n))
    entries = [
        CatalogEntry(**entry.model_dump(), environments=provided.get(entry.id, [])) for entry in registry.entries
    ]
    return sorted(entries, key=lambda e: (-e.level.rank, e.id))
