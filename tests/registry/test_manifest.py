from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from compose_api.registry.manifest import (
    HPC_MINIMUM_LEVEL,
    SERVICE_BUNDLE,
    CurationLevel,
    Manifest,
    RegistryEntry,
    load_manifest,
)


def entry(entry_id: str, roots: list[str], **fields: object) -> RegistryEntry:
    return RegistryEntry.model_validate({
        "id": entry_id,
        "package": entry_id,
        "source": "https://example.org",
        "version": "1.0",
        "module_roots": roots,
        "level": "listed",
        **fields,
    })


def test_shipped_manifest_loads_and_every_entry_has_evidence_for_its_level() -> None:
    manifest = load_manifest()
    assert manifest.entries
    for e in manifest.entries:
        if e.level.at_least(CurationLevel.INSTALLABLE):
            assert e.evidence, f"{e.id} is at {e.level} with no evidence recorded"


def test_the_service_bundle_is_runnable() -> None:
    runnable = [
        e for e in load_manifest().entries if SERVICE_BUNDLE in e.bundles and e.level.at_least(HPC_MINIMUM_LEVEL)
    ]
    assert {e.id for e in runnable} >= {"pbsim-common", "pb-multiscale-actin"}


def test_levels_are_ordered() -> None:
    assert CurationLevel.CURATED.at_least(CurationLevel.TESTED)
    assert not CurationLevel.LISTED.at_least(CurationLevel.TESTED)
    assert CurationLevel.TESTED.at_least(CurationLevel.TESTED)


def test_an_entry_must_be_pinned() -> None:
    with pytest.raises(ValidationError, match="must be pinned"):
        RegistryEntry.model_validate({
            "id": "x",
            "package": "x",
            "source": "https://example.org",
            "module_roots": ["x"],
            "level": "listed",
        })


def test_duplicate_ids_are_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        Manifest(entries=[entry("a", ["a"]), entry("a", ["b"])])


def test_the_viva_copasi_and_tellurium_entries_are_alternatives_to_pbsim_common() -> None:
    """Two families provide COPASI and Tellurium steps with the same class names; pbsim-common's are the standard set
    the service runs (solvers.yaml), the viva ones alternatives until they are reconciled."""
    by_id = {e.id: e for e in load_manifest().entries}
    assert by_id["viva-copasi"].alternative_to == "pbsim-common"
    assert by_id["viva-tellurium"].alternative_to == "pbsim-common"
    assert by_id["pbsim-common"].alternative_to is None


@pytest.mark.parametrize(
    ("alternatives", "why"),
    [
        ({"b": "nope"}, "not another entry"),
        ({"b": "b"}, "not another entry"),
        ({"b": "a", "c": "b"}, "itself an alternative"),
    ],
)
def test_an_alternative_names_a_standard_entry(alternatives: dict[str, str], why: str) -> None:
    entries = [entry(i, [i], alternative_to=alternatives.get(i)) for i in ("a", "b", "c")]
    with pytest.raises(ValidationError, match=why):
        Manifest(entries=entries)


def test_an_alternative_and_its_standard_are_components() -> None:
    lib = entry("lib", [], kind="library", install={"pypi": "lib", "version": "1"})
    with pytest.raises(ValidationError, match="both components"):
        Manifest(entries=[lib, entry("b", ["b"], alternative_to="lib")])


def test_longest_module_root_wins() -> None:
    manifest = Manifest(entries=[entry("outer", ["pkg"]), entry("inner", ["pkg.sub"])])
    assert (found := manifest.entry_for_module("pkg.sub.mod")) is not None and found.id == "inner"
    assert (found := manifest.entry_for_module("pkg.other")) is not None and found.id == "outer"
    assert manifest.entry_for_module("pkgx.mod") is None


@pytest.mark.parametrize(
    ("install", "why"),
    [
        ({"pypi": "x"}, "exact `version`"),
        ({"git": "https://github.com/o/x", "commit": "main"}, "never a branch"),
        ({"git": "https://github.com/o/x", "commit": "26fa156"}, "40-character"),
        ({"pypi": "x", "version": "1", "git": "https://github.com/o/x", "commit": "a" * 40}, "exactly one"),
        ({}, "exactly one"),
    ],
)
def test_an_install_is_one_pinned_source(install: dict[str, object], why: str) -> None:
    with pytest.raises(ValidationError, match=why):
        entry("x", ["x"], install=install)


def test_an_install_names_its_distribution() -> None:
    pypi = entry("x", ["x"], install={"pypi": "Pb_Multiscale.Actin", "version": "1.3.1"}).install
    git = entry("y", ["y"], install={"git": "https://github.com/biosimulations/pbsim_common.git", "commit": "a" * 40})
    assert pypi is not None and pypi.name == "pb-multiscale-actin"
    assert git.install is not None and git.install.name == "pbsim-common"


def test_a_component_needs_module_roots_and_a_library_does_not() -> None:
    with pytest.raises(ValidationError, match="needs `module_roots`"):
        entry("x", [])
    library = entry("readdy", [], kind="library", conda={"readdy": "==2.0.13"})
    assert library.kind == "library" and library.install is None


def test_every_library_says_how_it_installs() -> None:
    for e in load_manifest().entries:
        if e.kind == "library":
            assert e.install is not None or e.conda, f"library {e.id} says nothing about how it installs"


def test_an_edited_manifest_is_read_again(tmp_path: Path) -> None:
    """Parsing is cached for each version of the file; an edit is read at the next call."""
    entry = {"id": "a", "package": "a", "source": "https://github.com/o/a", "version": "1", "level": "listed"}
    entry["kind"] = "library"  # no module roots needed
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump({"entries": [entry]}))
    assert [e.id for e in load_manifest(path, catalog_path=None).entries] == ["a"]
    assert load_manifest(path, catalog_path=None) is not load_manifest(path, catalog_path=None)  # each its own copy
    path.write_text(yaml.safe_dump({"entries": [entry, {**entry, "id": "b", "package": "b"}]}))
    assert [e.id for e in load_manifest(path, catalog_path=None).entries] == ["a", "b"]


GATED = {
    "component": "v2ecoli.processes.metabolism.Metabolism",
    "check": "step-outputs-replace",
    "reason": "gated by update_condition: fires once per scheduled solve, so its deltas count once",
    "evidence": "tests/test_metabolism_gate.py",
}


GIT = {"install": {"git": "https://github.com/vivarium-collective/v2ecoli", "commit": "e" * 40}}


def test_an_entry_accepts_a_finding_for_its_own_component_with_a_reason_and_evidence() -> None:
    (accepted,) = entry("v2ecoli", ["v2ecoli"], accepted_findings=[GATED], **GIT).accepted_findings
    assert (accepted.component, accepted.check) == (GATED["component"], GATED["check"])
    with pytest.raises(ValidationError, match="not its own"):
        entry("other", ["other"], accepted_findings=[GATED], **GIT)
    for missing in ("reason", "evidence"):
        with pytest.raises(ValidationError, match="needs a reason and its evidence"):
            entry("v2ecoli", ["v2ecoli"], accepted_findings=[{**GATED, missing: "  "}], **GIT)
    # its evidence is a path at a commit, so only an entry installed from git can name one
    with pytest.raises(ValidationError, match="checked at a git commit"):
        entry("v2ecoli", ["v2ecoli"], accepted_findings=[GATED])
