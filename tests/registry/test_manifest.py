import pytest
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


def test_longest_module_root_wins() -> None:
    manifest = Manifest(entries=[entry("outer", ["pkg"]), entry("inner", ["pkg.sub"])])
    assert (found := manifest.entry_for_module("pkg.sub.mod")) is not None and found.id == "inner"
    assert (found := manifest.entry_for_module("pkg.other")) is not None and found.id == "outer"
    assert manifest.entry_for_module("pkgx.mod") is None
