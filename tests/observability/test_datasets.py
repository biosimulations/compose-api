"""The pure rules for datasets: which paths are accepted, what an ``artifact.written`` event registers, and which
feeder wins (docs/plan-observability.md O5, O6)."""

from compose_api.observability.datasets import (
    ORIGIN_EVENT,
    ORIGIN_MANIFEST,
    ArtifactRecord,
    artifact_records,
    infer_kind,
    infer_media_type,
    merge,
    normalize_path,
)
from compose_api.observability.events import RunEvent

SHA = "ab" * 32


def test_paths_are_relative_to_the_experiment_directory() -> None:
    assert normalize_path("output/a.csv") == "output/a.csv"
    assert normalize_path("/experiment/output/a.csv") == "output/a.csv"
    assert normalize_path("file:///experiment/output/./x/../a.csv") == "output/a.csv"
    for outside in ("/etc/passwd", "../x", "output/../../x", "", "/experiment/..", "."):
        assert normalize_path(outside) is None, outside


def test_kind_and_media_type_come_from_the_suffix() -> None:
    assert (infer_kind("output/r.pber"), infer_kind("results.zip"), infer_kind("output/x.weird")) == (
        "results",
        "archive",
        "file",
    )
    assert infer_media_type("output/a.csv") == "text/csv"
    assert infer_media_type("output/x.weird") == "application/octet-stream"


def _event(component: str, **payload: object) -> RunEvent:
    return RunEvent(seq=1, source="s", ts="", component=component, event="artifact.written", payload=payload)


def test_artifact_events_become_records() -> None:
    records = artifact_records([
        _event("compose_api.job", uri="output/a.csv", bytes=10, sha256=SHA.upper()),
        _event("process_bigraph", uri="/experiment/output/a.csv", kind="table", name="Species", attributes={"n": 3}),
        _event("process_bigraph", uri="/scratch/elsewhere"),  # outside the experiment: ignored
        _event("process_bigraph", uri="output/b.csv", error="disk full"),
    ])
    assert [(r.path, r.origin) for r in records] == [
        ("output/a.csv", ORIGIN_MANIFEST),
        ("output/a.csv", ORIGIN_EVENT),
        ("output/b.csv", ORIGIN_EVENT),
    ]
    assert records[0].sha256 == SHA and records[0].size_bytes == 10
    assert records[1].kind == "table" and records[1].attributes == {"n": 3}
    assert records[2].available is False


def test_a_producers_view_hint_is_kept() -> None:
    (record,) = artifact_records([
        _event(
            "viva_pde_particle",
            uri="output/run.fenics",
            kind="results-bundle",
            view={"variable": "u"},
            attributes={"web": 1},
        ),
    ])
    assert record.attributes == {"web": 1, "view": {"variable": "u"}}


def test_bundles_and_stores_have_their_own_kind_and_media_type() -> None:
    assert (infer_kind("output/run.fenics"), infer_media_type("output/run.fenics")) == (
        "results-bundle",
        "application/vnd.vcell.results-bundle+zarr",
    )
    assert infer_media_type("output/t.zarr") == "application/x-zarr"


def test_a_simulators_event_wins_and_the_manifest_fills_in() -> None:
    manifest = ArtifactRecord(path="output/a.csv", origin=ORIGIN_MANIFEST, size_bytes=10, sha256=SHA)
    event = ArtifactRecord(path="output/a.csv", origin=ORIGIN_EVENT, kind="species", display_name="Species")

    row = merge(None, manifest)
    assert (row.kind, row.display_name, row.origin) == ("table", "a.csv", ORIGIN_MANIFEST)
    row = merge(row, event)  # the event refines it, keeping the manifest's size and checksum
    assert (row.kind, row.display_name, row.origin, row.size_bytes, row.sha256) == (
        "species",
        "Species",
        ORIGIN_EVENT,
        10,
        SHA,
    )
    again = merge(merge(None, event), manifest)  # in the other order, the manifest only fills in
    assert (again.kind, again.display_name, again.origin, again.size_bytes) == ("species", "Species", ORIGIN_EVENT, 10)
