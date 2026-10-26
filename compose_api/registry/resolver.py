"""Which environment a run uses when it names none (docs/plan-environment-composition.md, step 7a; D7.1 to D7.3).

A document's class addresses map to registry entries through their module roots (the longest root wins), and each
entry brings the library entries it `requires`. Among the environments this deployment offers, the first whose
entries cover that set is chosen:

1. the shared environment (``registry_env``), which runs everything a run named nothing for before step 7, so every
   document it covers keeps running there;
2. then the other environments, the fewest entries first, then by name.

A set no environment covers falls back to the shared environment until mash-ups are built (step 7b), so validation
reports what it lacks, exactly as before. Pure functions over the manifest and ``environments.yaml``.
"""

from collections.abc import Callable, Iterable

from compose_api.registry.environments import EnvironmentsFile, EnvironmentSpec, members_of
from compose_api.registry.manifest import Manifest


def needed_entries(targets: Iterable[str], manifest: Manifest) -> set[str]:
    """The registry entries the classes ``targets`` (``<module>.<Class>``) come from, with what they require. A class
    under no entry adds nothing: validation refuses it."""
    found = set()
    for target in targets:
        module = target.rpartition(".")[0]
        entry = manifest.entry_for_module(module) if module else None
        if entry is not None:
            found.add(entry.id)
    return manifest.with_requirements(found)


def choose_environment(
    needed: set[str],
    manifest: Manifest,
    environments: EnvironmentsFile,
    offered: Callable[[EnvironmentSpec], bool] = lambda spec: True,
) -> EnvironmentSpec:
    """The environment a run needing ``needed`` uses: the shared one if it covers them, else the smallest offered one
    that does, else (until step 7b) the shared one, whose validation then names what is missing."""
    shared = next(spec for spec in environments.environments if spec.kind == "shared")
    candidates = [spec for spec in environments.environments if spec is shared or offered(spec)]
    covering = [spec for spec in candidates if needed <= members_of(spec, manifest)]
    if not covering:
        return shared
    return min(covering, key=lambda spec: (spec is not shared, len(members_of(spec, manifest)), spec.name))
