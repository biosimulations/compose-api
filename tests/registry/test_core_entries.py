"""The engine's own classes as a `core` entry (docs/plan-environment-composition.md, 7c-1, D7c.2): a document names
process-bigraph's emitters fully qualified, `local:process_bigraph.emitter.RAMEmitter`, and every composed version
provides them without listing them."""

import pytest

from compose_api.environments.contents import version_roots
from compose_api.registry.environments import EnvironmentSpec, load_environments, members_of, spec_problems
from compose_api.registry.manifest import CurationLevel, RegistryEntry, load_manifest
from compose_api.registry.resolver import choose_environment, needed_entries
from compose_api.registry.validation import Standing, check_address
from compose_api.simulation.models import EnvironmentVersion, VersionState

RAM = "local:process_bigraph.emitter.RAMEmitter"
COPASI = "local:pbsim_common.simulators.copasi_process.CopasiUTCStep"
COMPOSED = Standing(label="registry_env@5", members=frozenset({"pbsim-common", "tellurium"}))


def _reason(address: str, standing: Standing | None = None, environment: str = "registry_env") -> str | None:
    violation = check_address(address, "doc.pbg", load_manifest(), standing, environment)
    return violation.reason if violation is not None else None


def test_the_emitters_entry_is_the_cores_own_version_and_installs_nothing() -> None:
    manifest = load_manifest()
    [core] = manifest.core_entries()
    assert core.module_roots == ["process_bigraph.emitter"] and core.install is None and not core.conda
    composition = load_environments().composition
    assert composition is not None and core.version == composition.core["process-bigraph"]
    with pytest.raises(ValueError, match="no install"):
        RegistryEntry.model_validate({**core.model_dump(), "install": {"pypi": "process-bigraph", "version": "1.9.1"}})


def test_a_composed_version_admits_the_fully_qualified_emitters() -> None:
    assert _reason(RAM, COMPOSED) is None
    assert _reason("local:process_bigraph.emitter.JSONEmitter", COMPOSED) is None
    # not one of its members, and admitted all the same: every composed image installs the core
    assert "process-bigraph-emitters" not in COMPOSED.members  # type: ignore[operator]
    assert _reason(COPASI, COMPOSED) is None


def test_a_prebuilt_image_admits_them_when_it_bundles_the_core() -> None:
    assert _reason(RAM, environment="viva-pde-particle") is None
    reason = _reason(RAM, environment="registry_env")  # no composed standing: registry_env@1, built the old way
    assert reason is not None and "provided by composed versions" in reason
    old = Standing(label="registry_env@1")  # a version that is not composed has no members
    assert "registry_env@1 is not one" in (_reason(RAM, old) or "")


def test_the_short_name_stays_refused() -> None:
    assert "short names are ambiguous" in (_reason("local:RAMEmitter", COMPOSED) or "")
    assert "short names are ambiguous" in (_reason("local:ram-emitter", COMPOSED) or "")


def test_the_core_never_decides_where_a_run_goes() -> None:
    manifest = load_manifest()
    alone = needed_entries(["process_bigraph.emitter.RAMEmitter"], manifest)
    assert alone == set()
    with_copasi = needed_entries(
        ["process_bigraph.emitter.RAMEmitter", "pbsim_common.simulators.copasi_process.CopasiUTCStep"], manifest
    )
    assert "process-bigraph-emitters" not in with_copasi and "pbsim-common" in with_copasi
    assert choose_environment(with_copasi, manifest, load_environments()).name == "registry_env"
    # no environment lists it among its members, so it neither covers nor names a mash-up
    for spec in load_environments().environments:
        assert "process-bigraph-emitters" not in members_of(spec, manifest)


def test_an_environment_may_not_list_a_core_entry() -> None:
    spec = EnvironmentSpec(
        name="core-listed", kind="mash-up", python=["python"], entries=["pbsim-common", "process-bigraph-emitters"]
    )
    problems = spec_problems(spec, load_manifest(), bundled=False)
    assert any("is core" in p for p in problems), problems


def test_a_composed_version_reads_the_cores_classes_back() -> None:
    version = EnvironmentVersion(
        database_id=1,
        environment_id=1,
        environment="mash-x",
        number=1,
        state=VersionState.READY,
        simulator_id=1,
        spec={"entries": [{"id": "pbsim-common"}]},
    )
    assert version_roots(version) == ["pbsim_common", "process_bigraph.emitter"]


def test_a_core_entry_needs_module_roots() -> None:
    with pytest.raises(ValueError, match="module_roots"):
        RegistryEntry(
            id="x", package="x", source="s", kind="core", version="1", level=CurationLevel.TESTED, module_roots=[]
        )


def test_viva_pde_particle_and_copasi_make_a_mash_up_that_admits_them() -> None:
    """The motivating mash-up (composition 7c): viva-pde-particle's ensemble beside pbsim-common's COPASI step, with
    process-bigraph's emitter. No declared environment covers both, so a mash-up of exactly what they need is made,
    and its version admits every address. Locked, built and run in Docker on 2026-10-27 (7c-4)."""
    from compose_api.environments import lifecycle
    from compose_api.registry.resolver import covering_environment

    manifest = load_manifest()
    targets = ["viva_pde_particle.ensemble.EnsembleRunner", COPASI[6:], RAM[6:]]
    needed = needed_entries(targets, manifest)
    assert {"viva-pde-particle", "smoldyn-vcell", "pbsim-common", "python-copasi"} <= needed
    assert "process-bigraph-emitters" not in needed
    assert covering_environment(needed, manifest, load_environments()) is None
    assert lifecycle.composable(needed, manifest) == []
    standing = Standing(label=f"{lifecycle.mash_up_name(needed)}@1", members=frozenset(needed))
    for address in ("local:viva_pde_particle.ensemble.EnsembleRunner", COPASI, RAM):
        assert _reason(address, standing) is None, address
