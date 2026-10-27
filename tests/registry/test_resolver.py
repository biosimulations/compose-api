"""Inferring a run's environment (docs/plan-environment-composition.md, step 7a; D7.1 to D7.3): addresses to entries,
with what they require, then the environment that covers them."""

import pytest

from compose_api.registry.environments import EnvironmentsFile, EnvironmentSpec, load_environments, members_of
from compose_api.registry.manifest import CurationLevel, Manifest, RegistryEntry, load_manifest
from compose_api.registry.resolver import choose_environment, needed_entries

COPASI = "pbsim_common.simulators.copasi_process.CopasiUTCStep"
PDE = "viva_pde_particle.processes.PDE"
EVERYWHERE = load_environments()


def test_a_pbsim_class_needs_pbsim_common_and_the_engines_it_requires() -> None:
    assert needed_entries([COPASI], load_manifest()) == {
        "pbsim-common",
        "tellurium",
        "python-copasi",
        "pyvcell",
        "libvcell",
    }
    assert needed_entries(["numpy.Solver", "Short"], load_manifest()) == set()  # under no entry: validation refuses


def test_every_class_registry_env_provides_still_runs_there() -> None:
    """Step 7a changes no run: everything a run named nothing for before still goes to registry_env."""
    manifest = load_manifest()
    shared = next(e for e in EVERYWHERE.environments if e.name == "registry_env")
    for entry_id in members_of(shared, manifest):
        entry = next(e for e in manifest.entries if e.id == entry_id)
        for root in entry.module_roots:
            needed = needed_entries([f"{root}.module.Class"], manifest)
            assert choose_environment(needed, manifest, EVERYWHERE).name == "registry_env", entry_id
    assert choose_environment(set(), manifest, EVERYWHERE).name == "registry_env"  # an SBML model names no class


def test_a_prebuilt_environments_classes_go_to_it_when_it_is_offered() -> None:
    manifest = load_manifest()
    needed = needed_entries([PDE], manifest)
    # its requirements come with it (composition 7c-4: it is composable now), and its image provides them, so a
    # document of its classes alone still runs in its prebuilt image (D7c.3), not in a mash-up
    assert "viva-pde-particle" in needed and "smoldyn-vcell" in needed
    assert choose_environment(needed, manifest, EVERYWHERE).name == "viva-pde-particle"
    # not offered here: the shared environment, whose validation then says the entry is not installed in it
    assert choose_environment(needed, manifest, EVERYWHERE, offered=lambda spec: False).name == "registry_env"


def test_entries_no_environment_covers_fall_back_to_the_shared_one_until_mash_ups() -> None:
    manifest = load_manifest()
    assert choose_environment(needed_entries([PDE, COPASI], manifest), manifest, EVERYWHERE).name == "registry_env"


def _entry(entry_id: str, bundles: list[str]) -> RegistryEntry:
    return RegistryEntry(
        id=entry_id, package=entry_id, source=f"https://example.org/{entry_id}", version="1", module_roots=[entry_id],
        level=CurationLevel.TESTED, bundles=bundles,
    )  # fmt: skip


def test_the_smallest_covering_environment_wins_after_the_shared_one() -> None:
    manifest = Manifest(entries=[_entry("a", ["shared", "big"]), _entry("b", ["big", "small"]), _entry("c", ["big"])])
    environments = EnvironmentsFile.model_validate({
        "describe": EVERYWHERE.describe.model_dump(),
        "environments": [
            {"name": "shared", "kind": "shared", "python": ["python"]},
            {"name": "big", "kind": "prebuilt", "python": ["python"]},
            {"name": "small", "kind": "prebuilt", "python": ["python"]},
        ],
    })
    assert choose_environment({"a"}, manifest, environments).name == "shared"
    assert choose_environment({"b"}, manifest, environments).name == "small"
    assert choose_environment({"a", "b"}, manifest, environments).name == "big"
    assert isinstance(environments.environments[0], EnvironmentSpec)


def test_requires_must_name_entries_the_manifest_has() -> None:
    entry = _entry("a", []).model_copy(update={"requires": ["nowhere"]})
    with pytest.raises(ValueError, match="nowhere"):
        Manifest(entries=[entry])
    assert Manifest(entries=[entry.model_copy(update={"requires": ["b"]}), _entry("b", [])]).with_requirements({
        "a"
    }) == {"a", "b"}
