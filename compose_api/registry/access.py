"""Private registry entries: who may see and use what is made of them (docs/plan-private-repo-usage.md, A and B).

An entry with an `access_role` belongs to a private repository. A caller who holds that role uses it like any other
entry. For every other caller it does not exist: its classes are refused as unregistered ones are, and every environment
that has it among its members is reported as not found, with that environment's versions and simulators. There is no
administrator bypass: an operator who needs access is given the role.

An environment needs the roles of all its members (``environment_roles``). A version also needs the roles its spec
recorded when it was made (``version_roles``), so a later manifest edit never narrows it. A run keeps the roles of the
version it ran in (``simulation.access_roles``), and the read policy checks them first (compose_api.authorization).
"""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from compose_api.registry.environments import EnvironmentsFile, EnvironmentSpec, load_environments, members_of
from compose_api.registry.manifest import Manifest, RegistryEntry, load_manifest

if TYPE_CHECKING:
    from compose_api.db.database_service import DatabaseService

# what a private entry's compliance case may hold in this public repository: its document, not data (decision 2)
_CASE_FILES = (".pbg", ".json")


def entry_roles(entry_ids: Iterable[str], manifest: Manifest) -> frozenset[str]:
    """The roles needed to use these entries: each private one's `access_role`."""
    wanted = set(entry_ids)
    return frozenset(e.access_role for e in manifest.entries if e.id in wanted and e.access_role is not None)


def may_use(roles: Iterable[str], caller_roles: frozenset[str]) -> bool:
    """Whether a caller holding ``caller_roles`` may use what needs ``roles``; an anonymous caller holds none."""
    return frozenset(roles) <= caller_roles


def usable(manifest: Manifest, caller_roles: frozenset[str]) -> Manifest:
    """The manifest as a caller may use it: without the private entries whose role the caller lacks, so their classes
    are refused as unregistered ones are, and they never join an environment made for the caller."""
    kept = [e for e in manifest.entries if e.access_role is None or e.access_role in caller_roles]
    if len(kept) == len(manifest.entries):
        return manifest
    # still a valid manifest: no public entry requires a private one (``problems``)
    return Manifest.model_construct(entries=kept)


def environment_roles(spec: EnvironmentSpec, manifest: Manifest) -> frozenset[str]:
    """The roles needed to see an environment: those of every entry it provides."""
    return entry_roles(members_of(spec, manifest), manifest)


def version_roles(spec: Mapping[str, Any] | None, manifest: Manifest) -> frozenset[str]:
    """The roles needed to see a composed version: those its spec recorded when it was made, and its entries' now."""
    recorded = frozenset((spec or {}).get("access_roles") or [])
    entries = [str(e["id"]) for e in (spec or {}).get("entries") or [] if isinstance(e, Mapping) and "id" in e]
    return recorded | entry_roles(entries, manifest)


def run_roles(environment: str, spec: Mapping[str, Any] | None, manifest: Manifest) -> frozenset[str]:
    """The roles a run's readers need: those of the version it runs in (``spec``) and, for a declared environment
    (a prebuilt image lists no entries), those of the entries it provides."""
    declared = next((s for s in load_environments().environments if s.name == environment), None)
    own = environment_roles(declared, manifest) if declared is not None else frozenset()
    return version_roles(spec, manifest) | own


async def recorded_roles(database_service: "DatabaseService | None") -> dict[str, frozenset[str]]:
    """The roles each environment's versions recorded when they were made, by environment: what it keeps needing after
    its entry's role is renamed or the entry leaves the manifest (``version_roles``)."""
    found: dict[str, frozenset[str]] = {}
    links = await database_service.get_environments_db().version_links() if database_service is not None else []
    for link in links:
        if link.access_roles:
            found[link.ref.environment] = found.get(link.ref.environment, frozenset()) | link.access_roles
    return found


async def hidden_environments(
    database_service: "DatabaseService | None", caller_roles: frozenset[str]
) -> frozenset[str]:
    """The environments, declared or mash-up, a caller may not see: those whose entries, or whose versions as they
    recorded it, need a role the caller lacks. Empty while nothing is or was private."""
    manifest = load_manifest()
    recorded = await recorded_roles(database_service)
    hidden = {name for name, roles in recorded.items() if not may_use(roles, caller_roles)}
    if not any(entry.access_role for entry in manifest.entries):
        return frozenset(hidden)
    hidden |= {
        spec.name
        for spec in load_environments().environments
        if not may_use(environment_roles(spec, manifest), caller_roles)
    }
    if database_service is not None:
        for record in await database_service.get_environments_db().environments():
            if record.kind == "mash-up" and not may_use(entry_roles(record.entries or [], manifest), caller_roles):
                hidden.add(record.name)
    return frozenset(hidden)


async def hidden_simulators(database_service: "DatabaseService | None", hidden: frozenset[str]) -> frozenset[int]:
    """The simulators that are a version of an environment in ``hidden``."""
    if not hidden or database_service is None:
        return frozenset()
    links = await database_service.get_environments_db().version_links()
    return frozenset(link.simulator_id for link in links if link.simulator_id and link.ref.environment in hidden)


async def simulators_hidden_from(
    database_service: "DatabaseService | None", caller_roles: frozenset[str]
) -> frozenset[int]:
    """The simulators a caller may not see: the versions of the environments hidden from them."""
    return await hidden_simulators(database_service, await hidden_environments(database_service, caller_roles))


def _entry_problems(entry: RegistryEntry, manifest: Manifest) -> list[str]:
    """How a private entry would show through another entry: core, an alternative, required by a public entry, or a
    module root another entry shares (the longest root claims a module)."""
    found = []
    if entry.kind == "core":
        found.append(f"{entry.id}: a private entry cannot be core, which every composed environment provides")
    if entry.alternative_to is not None:
        found.append(f"{entry.id}: a private entry is no alternative to a public one")
    for other in (e for e in manifest.entries if e.id != entry.id):
        if other.alternative_to == entry.id:
            found.append(f"{other.id}: is an alternative to the private entry {entry.id}")
        if entry.id in other.requires and other.access_role != entry.access_role:
            found.append(f"{other.id}: requires the private entry {entry.id} but is not private to its role")
        found += [
            f"{entry.id}: its module root {mine} overlaps {other.id}'s {theirs}"
            for mine in entry.module_roots
            for theirs in other.module_roots
            if mine == theirs or mine.startswith(theirs + ".") or theirs.startswith(mine + ".")
        ]
    return found


def _case_problems(entry: RegistryEntry, compliance_dir: Path) -> list[str]:
    """A file in a private entry's compliance case other than its document: this repository is public (decision 2)."""
    root = compliance_dir / entry.id
    files = sorted(path for path in root.rglob("*") if path.is_file()) if root.is_dir() else []
    return [
        f"{entry.id}: its compliance case holds {path.relative_to(compliance_dir)}, not a document"
        for path in files
        if path.name != "case.yaml" and path.suffix not in _CASE_FILES
    ]


def problems(
    manifest: Manifest, environments: EnvironmentsFile, solver_targets: Iterable[tuple[str, str]], compliance_dir: Path
) -> list[str]:
    """What would let a private entry show through to callers without its role; empty when nothing would. Each rule
    keeps it out of what every caller uses: the shared environment, solvers (so SED-ML, suites and sources), another
    entry's requirements, alternatives, or a module another entry claims. ``solver_targets`` is each solver's
    (environment, class)."""
    private = [entry for entry in manifest.entries if entry.access_role is not None]
    found = [p for entry in private for p in _entry_problems(entry, manifest) + _case_problems(entry, compliance_dir)]
    for spec in (s for s in environments.environments if s.kind == "shared"):
        held = sorted(members_of(spec, manifest) & {entry.id for entry in private})
        if held:
            found.append(f"{spec.name}: the shared environment cannot hold private entries {held}")
    by_name = {spec.name: spec for spec in environments.environments}
    for environment, target in solver_targets:
        runs_in = by_name.get(environment)
        if runs_in is not None and environment_roles(runs_in, manifest):
            found.append(f"a solver runs in {environment}, which holds private entries")
        owner = manifest.entry_for_module(target.removeprefix("local:").rpartition(".")[0])
        if owner is not None and owner.access_role is not None:
            found.append(f"a solver's class {target} is in the private entry {owner.id}")
    return found
