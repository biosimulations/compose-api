"""Which environment a run uses when it names none (docs/plan-environment-composition.md, step 7a; D7.1 to D7.3).

A document's class addresses map to registry entries through their module roots (the longest root wins), and each
entry brings the library entries it `requires`. Among the environments this deployment offers, the first whose
entries cover that set is chosen:

1. the shared environment (``registry_env``), which runs everything a run named nothing for before step 7, so every
   document it covers keeps running there;
2. then the other environments, the fewest entries first, then by name.

Then the mash-ups the database holds (step 7b). A set nothing covers is either made a mash-up (by the run route, from
``environments/lifecycle.py``) or falls back to the shared environment, whose validation reports what it lacks.
Pure functions over the manifest, ``environments.yaml`` and the mash-ups given.
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


def covering_environment(
    needed: set[str],
    manifest: Manifest,
    environments: EnvironmentsFile,
    offered: Callable[[EnvironmentSpec], bool] = lambda spec: True,
    mash_ups: Iterable[EnvironmentSpec] = (),
) -> EnvironmentSpec | None:
    """The environment whose entries cover ``needed``, if one does: the shared one, then the other declared ones this
    deployment offers, then the mash-ups (D7.3); among each, the fewest entries, then the name."""
    shared = next(spec for spec in environments.environments if spec.kind == "shared")
    declared = [spec for spec in environments.environments if spec is shared or offered(spec)]
    covering = [spec for spec in [*declared, *mash_ups] if needed <= members_of(spec, manifest)]
    if not covering:
        return None
    return min(
        covering,
        key=lambda spec: (spec is not shared, spec.kind == "mash-up", len(members_of(spec, manifest)), spec.name),
    )


def choose_environment(
    needed: set[str],
    manifest: Manifest,
    environments: EnvironmentsFile,
    offered: Callable[[EnvironmentSpec], bool] = lambda spec: True,
) -> EnvironmentSpec:
    """The covering environment, or else the shared one, whose validation then names what is missing."""
    shared = next(spec for spec in environments.environments if spec.kind == "shared")
    return covering_environment(needed, manifest, environments, offered) or shared
