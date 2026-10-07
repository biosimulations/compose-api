"""The datasets a run advertises: read models, and the pure rules for registering them (docs/plan-observability.md
O5, O6).

Both feeders arrive as ``artifact.written`` events in the run's event stream, in viva-core's payload
(``viva_core/datasets/registry.py``): ``{uri, kind?, name?, bytes?, sha256?, attributes?, error?}``.

- **The manifest:** the job script emits one per file it finds under ``output/`` after the run (and one for
  ``results.zip``), from ``component="compose_api.job"``. Every simulator gets datasets this way.
- **The simulator:** an engine that knows what it wrote emits its own, with a kind, a name and attributes. These
  refine the manifest's row for the same path and win over it.

A dataset's ``path`` is relative to the run's experiment directory (``output/rho.npy``), never an absolute or host
path, so the store can move (O6).
"""

from __future__ import annotations

import mimetypes
import posixpath
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from compose_api.observability.events import RunEvent

ARTIFACT_EVENT = "artifact.written"
MANIFEST_COMPONENT = "compose_api.job"
ORIGIN_MANIFEST, ORIGIN_EVENT = "manifest", "event"

#: The container's view of the experiment directory (the job script binds it there).
CONTAINER_ROOT = "/experiment/"

_KINDS = {
    ".pber": "results",
    ".csv": "table",
    ".tsv": "table",
    ".parquet": "table",
    ".h5": "hdf5",
    ".hdf5": "hdf5",
    ".nc": "netcdf",
    ".zarr": "zarr",
    ".npy": "array",
    ".npz": "array",
    ".vtu": "mesh",
    ".vtk": "mesh",
    ".png": "figure",
    ".svg": "figure",
    ".pdf": "figure",
    ".html": "figure",
    ".json": "json",
    ".zip": "archive",
    ".omex": "archive",
    ".txt": "text",
    ".log": "log",
    ".out": "log",
}
_MEDIA_TYPES = {
    ".out": "text/plain",
    ".pber": "application/x-ndjson",
    ".parquet": "application/vnd.apache.parquet",
    ".npy": "application/x-npy",
}


class Dataset(BaseModel):
    """A file a run produced, readable by anyone who may read its simulation (O7)."""

    id: str
    simulation_id: int
    path: str  # relative to the run's experiment directory, e.g. "output/rho.npy"
    kind: str
    media_type: str
    display_name: str
    size_bytes: int | None = None
    sha256: str | None = None
    attributes: dict[str, object] = Field(default_factory=dict)
    origin: str  # "manifest" (the job script found it) or "event" (the simulator announced it)
    span_id: str | None = None
    available: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class DatasetPage(BaseModel):
    datasets: list[Dataset]
    total: int
    next_offset: int | None = None


@dataclass
class ArtifactRecord:
    """One ``artifact.written`` event, normalized."""

    path: str
    origin: str
    kind: str | None = None
    display_name: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    media_type: str | None = None
    attributes: dict[str, object] = field(default_factory=dict)
    span_id: str | None = None
    available: bool = True


def normalize_path(uri: str) -> str | None:
    """A path relative to the experiment directory, or None if it points outside it.

    ``/experiment/output/x`` (the container's view) and ``output/x`` both give ``output/x``; ``file://`` is dropped.
    Any other absolute path, and anything that climbs out with ``..``, is refused.
    """
    path = uri.removeprefix("file://").strip()
    if path.startswith(CONTAINER_ROOT):
        path = path[len(CONTAINER_ROOT) :]
    elif path.startswith("/") or not path:
        return None
    normal = posixpath.normpath(path)
    if normal in (".", "..") or normal.startswith("../"):
        return None
    return normal


def infer_kind(path: str) -> str:
    return _KINDS.get(posixpath.splitext(path)[1].lower(), "file")


def infer_media_type(path: str) -> str:
    suffix = posixpath.splitext(path)[1].lower()
    return _MEDIA_TYPES.get(suffix) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def artifact_record(event: RunEvent) -> ArtifactRecord | None:
    """The record an ``artifact.written`` event describes, or None if it names no usable path."""
    payload = event.payload or {}
    uri = payload.get("uri")
    path = normalize_path(uri) if isinstance(uri, str) else None
    if path is None:
        return None
    attributes = payload.get("attributes")
    kind, name, sha = payload.get("kind"), payload.get("name"), payload.get("sha256")
    media_type = payload.get("media_type")
    return ArtifactRecord(
        path=path,
        origin=ORIGIN_MANIFEST if event.component == MANIFEST_COMPONENT else ORIGIN_EVENT,
        kind=kind if isinstance(kind, str) and kind else None,
        display_name=name if isinstance(name, str) and name else None,
        size_bytes=_int(payload.get("bytes")),
        sha256=sha.lower() if isinstance(sha, str) and len(sha) == 64 else None,
        media_type=media_type if isinstance(media_type, str) and media_type else None,
        attributes={k: v for k, v in attributes.items() if k != "origin"} if isinstance(attributes, dict) else {},
        span_id=event.span_id,
        available=not payload.get("error"),
    )


def artifact_records(events: list[RunEvent]) -> list[ArtifactRecord]:
    return [r for r in (artifact_record(e) for e in events if e.event == ARTIFACT_EVENT) if r is not None]


@dataclass
class DatasetRow:
    """What is stored for a dataset, before and after a registration is merged in."""

    path: str
    origin: str
    kind: str
    media_type: str
    display_name: str
    size_bytes: int | None
    sha256: str | None
    attributes: dict[str, object]
    span_id: str | None
    available: bool


def merge(existing: DatasetRow | None, record: ArtifactRecord) -> DatasetRow:
    """The row after ``record`` is registered: a simulator's event wins over the manifest; the manifest only fills in
    what an event left out (its size and checksum)."""
    fresh = DatasetRow(
        path=record.path,
        origin=record.origin,
        kind=record.kind or infer_kind(record.path),
        media_type=record.media_type or infer_media_type(record.path),
        display_name=record.display_name or posixpath.basename(record.path),
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        attributes=record.attributes,
        span_id=record.span_id,
        available=record.available,
    )
    if existing is None:
        return fresh
    if existing.origin == ORIGIN_EVENT and record.origin == ORIGIN_MANIFEST:
        existing.size_bytes = existing.size_bytes if existing.size_bytes is not None else record.size_bytes
        existing.sha256 = existing.sha256 or record.sha256
        existing.available = record.available
        return existing
    fresh.size_bytes = fresh.size_bytes if fresh.size_bytes is not None else existing.size_bytes
    fresh.sha256 = fresh.sha256 or existing.sha256
    return fresh
