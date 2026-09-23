"""The catalog ingest, without the network: build, round-trip, and precedence under the curated manifest."""

import datetime
from pathlib import Path

import yaml

from compose_api.registry.catalog import CatalogModule, build_entries, read_catalog, write_catalog
from compose_api.registry.manifest import CurationLevel, load_manifest
from compose_api.registry.validation import find_violations
from compose_api.simulation.models import SimulationFileType

TODAY = datetime.date(2026, 9, 23)
LATER = datetime.date(2026, 10, 1)


def module(name: str, package: str | None = None) -> CatalogModule:
    return CatalogModule(
        name=name,
        source=f"https://github.com/vivarium-collective/{name}.git",
        package=package or name.replace("-", "_"),
    )


def test_every_module_becomes_a_pinned_listed_entry() -> None:
    (entry,) = build_entries([module("viva-tellurium")], {"viva-tellurium": "a" * 40}, {}, TODAY)
    assert entry.level == CurationLevel.LISTED
    assert entry.commit == "a" * 40
    assert entry.module_roots == ["viva_tellurium"]
    assert TODAY.isoformat() in entry.evidence[0]


def test_an_unchanged_pin_keeps_its_entry_and_a_moved_one_is_restamped() -> None:
    first = build_entries([module("a"), module("b")], {"a": "1" * 40, "b": "2" * 40}, {}, TODAY)
    previous = {e.id: e for e in first}
    second = build_entries([module("a"), module("b")], {"a": "1" * 40, "b": "3" * 40}, previous, LATER)
    by_id = {e.id: e for e in second}
    assert by_id["a"] == previous["a"]
    assert by_id["b"].commit == "3" * 40
    assert LATER.isoformat() in by_id["b"].evidence[0]


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "catalog.yaml"
    entries = build_entries([module("viva-copasi")], {"viva-copasi": "c" * 40}, {}, TODAY)
    write_catalog(entries, path)
    assert path.read_text().startswith("# GENERATED")
    assert read_catalog(path) == {"viva-copasi": entries[0]}


def test_curated_manifest_takes_precedence_over_the_catalog(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump({
            "entries": [
                {
                    "id": "viva-copasi",
                    "package": "viva-copasi",
                    "source": "https://github.com/vivarium-collective/viva-copasi",
                    "commit": "d" * 40,
                    "module_roots": ["viva_copasi"],
                    "level": "tested",
                    "bundles": ["registry_env"],
                    "evidence": ["test"],
                }
            ]
        })
    )
    catalog = tmp_path / "catalog.yaml"
    write_catalog(
        build_entries(
            [module("viva-copasi"), module("viva-smoldyn")],
            {"viva-copasi": "c" * 40, "viva-smoldyn": "s" * 40},
            {},
            TODAY,
        ),
        catalog,
    )
    loaded = {e.id: e for e in load_manifest(manifest, catalog).entries}
    assert loaded["viva-copasi"].level == CurationLevel.TESTED
    assert loaded["viva-smoldyn"].level == CurationLevel.LISTED


def test_shipped_catalog_entries_are_listed_and_refused_on_the_service(tmp_path: Path) -> None:
    """Every catalog wrapper is visible in the registry, and none of them runs on HPC until it is raised."""
    catalog = read_catalog()
    assert catalog, "catalog.yaml is empty; run `python -m compose_api.registry.catalog`"
    assert all(e.level == CurationLevel.LISTED and e.commit for e in catalog.values())

    root = catalog["viva-tellurium"].module_roots[0]
    path = tmp_path / "doc.pbg"
    path.write_text(f'{{"state": {{"s": {{"_type": "step", "address": "local:{root}.processes.Step"}}}}}}')
    (violation,) = find_violations(path, SimulationFileType.PBG, load_manifest())
    assert "level `listed`" in violation.reason
