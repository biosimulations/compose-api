"""A run's events and spans: the read models, and the pure parsing and folding the ingester uses.

Ported from viva-core (``viva_core/events/models.py`` and the pure half of ``viva_core/events/ingest.py``), which
reads the same process-bigraph event schema (``process_bigraph/events.py``, schema v1). No storage and no I/O here,
so every rule is unit-testable on its own. See docs/plan-observability.md (O3, O4).
"""

from __future__ import annotations

import datetime
import json

from pydantic import BaseModel, Field

#: Never stored: the engine's heartbeat.
UNSTORED_EVENTS: frozenset[str] = frozenset({"tick"})
#: Never stored either: ``debug`` means "stream only", so a per-step event a simulator adds is bounded by default.
UNSTORED_LEVELS: frozenset[str] = frozenset({"debug"})

SPAN_START_EVENTS: frozenset[str] = frozenset({"span.start", "span_start"})
SPAN_END_EVENTS: frozenset[str] = frozenset({"span.end", "span_end"})
SPAN_EVENTS: frozenset[str] = SPAN_START_EVENTS | SPAN_END_EVENTS

#: The status the ingester gives a span still open when its run ended. Its ``end_ts`` is when that was noticed, not
#: when the work stopped, so it has no duration. A ``span.end`` that arrives later still wins.
UNENDED_SPAN_STATUS = "unknown"


class RunEvent(BaseModel):
    """One structured event of a run, from the API, the job script or the simulator's engine."""

    cursor: int | None = None  # the stored row id: pass back as ``after`` to page forward
    seq: int
    source: str  # who wrote it: "api", "job-<slurm id>", or the engine's "<host>-<pid>"
    ts: str  # ISO 8601 UTC
    component: str  # the emitting code: "compose_api.api", "compose_api.job", "process_bigraph", ...
    event: str
    level: str = "info"
    baggage: dict[str, object] | None = None
    global_time: float | None = None
    wall_time: float | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    payload: dict[str, object] | None = None
    tags: dict[str, object] | None = None


class RunSpan(BaseModel):
    """A node of a run's trace tree, folded from ``span.start`` / ``span.end`` events. ``end_ts`` is None while open."""

    span_id: str
    parent_span_id: str | None = None
    name: str
    attrs: dict[str, object] | None = None
    start_ts: str | None = None
    end_ts: str | None = None
    duration_s: float | None = None
    status: str | None = None  # ok | error | unknown, None while open
    error: str | None = None


class SpanTree(BaseModel):
    """A span with its own events (those whose ``span_id`` is the span's) and its children, by start time."""

    span: RunSpan
    events: list[RunEvent] = Field(default_factory=list)
    children: list[SpanTree] = Field(default_factory=list)


class RunEventPage(BaseModel):
    """A page of a simulation's events, in the order they were recorded.

    ``next_cursor`` is the ``after`` for the next page, None at the end.
    """

    simulation_id: int
    trace_id: str | None  # None: the simulation has no run yet, or it predates tracing
    events: list[RunEvent]
    next_cursor: int | None = None


class RunTraceTree(BaseModel):
    """A simulation's spans as a forest, each span carrying its own events."""

    simulation_id: int
    trace_id: str | None
    roots: list[SpanTree]


# ---------------------------------------------------------------- parsing


def parse_timestamp(value: object) -> datetime.datetime | None:
    """An event ``ts`` (ISO 8601, ``Z`` or an offset) as an aware UTC datetime, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=datetime.UTC) if parsed.tzinfo is None else parsed.astimezone(datetime.UTC)


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, int | float) else None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_event_line(line: str, *, expected_trace_id: str | None = None) -> RunEvent | None:
    """One JSON line as a :class:`RunEvent`, or None when it is not a usable event: not a JSON object, no ``event``
    name or ``seq``, or stamped with a trace other than ``expected_trace_id``."""
    text = line.strip()
    if not text:
        return None
    try:
        raw = json.loads(text)
    except ValueError:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("event"), str):
        return None
    trace_id = raw.get("trace_id")
    if expected_trace_id and isinstance(trace_id, str) and trace_id and trace_id != expected_trace_id:
        return None
    seq = _as_int(raw.get("seq"))
    if seq is None:
        return None
    payload, tags, baggage = raw.get("payload"), raw.get("tags"), raw.get("baggage")
    return RunEvent(
        seq=seq,
        source=str(raw.get("source") or "unknown"),
        ts=str(raw.get("ts") or ""),
        component=str(raw.get("component") or "process_bigraph"),
        event=raw["event"],
        level=str(raw.get("level") or "info"),
        baggage=baggage if isinstance(baggage, dict) and baggage else None,
        global_time=_as_float(raw.get("global_time")),
        wall_time=_as_float(raw.get("wall_time")),
        span_id=_as_str(raw.get("span_id")),
        parent_span_id=_as_str(raw.get("parent_span_id")),
        payload=payload if isinstance(payload, dict) else None,
        tags=tags if isinstance(tags, dict) else None,
    )


def parse_complete_lines(data: bytes, *, expected_trace_id: str | None = None) -> tuple[list[RunEvent], int, int]:
    """The events in ``data`` up to its last newline, the bytes those lines span, and the count of lines skipped.

    A writer may be mid-line, so a trailing partial line is left for the next read: the caller advances its cursor by
    the bytes consumed, not by ``len(data)``.
    """
    end = data.rfind(b"\n") + 1
    events: list[RunEvent] = []
    bad = 0
    for line in data[:end].decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        event = parse_event_line(line, expected_trace_id=expected_trace_id)
        if event is None:
            bad += 1
        else:
            events.append(event)
    return events, end, bad


def storable_events(events: list[RunEvent]) -> list[RunEvent]:
    """The events that become rows: everything but heartbeats and ``debug``. Spans are folded from all of them."""
    return [e for e in events if e.event not in UNSTORED_EVENTS and e.level.lower() not in UNSTORED_LEVELS]


# ---------------------------------------------------------------- spans


def _span_for_event(spans: dict[str, RunSpan], event: RunEvent) -> RunSpan:
    payload = event.payload or {}
    name, attrs = payload.get("name"), payload.get("attrs")
    span = spans.get(event.span_id or "")
    if span is None:
        span = RunSpan(
            span_id=event.span_id or "",
            parent_span_id=event.parent_span_id,
            name=str(name or "span"),
            attrs=attrs if isinstance(attrs, dict) else None,
        )
        spans[span.span_id] = span
    if isinstance(name, str) and name:
        span.name = name
    if isinstance(attrs, dict) and attrs:
        span.attrs = attrs
    if event.parent_span_id and not span.parent_span_id:
        span.parent_span_id = event.parent_span_id
    start_ts = payload.get("start_ts")
    if isinstance(start_ts, str) and start_ts and not span.start_ts:
        span.start_ts = start_ts
    return span


def _apply_span_end(span: RunSpan, event: RunEvent) -> None:
    payload = event.payload or {}
    end_ts = payload.get("end_ts")
    span.end_ts = end_ts if isinstance(end_ts, str) and end_ts else event.ts
    span.duration_s = _as_float(payload.get("duration_s"))
    status = payload.get("status")
    span.status = str(status) if status else ("error" if event.level == "error" else "ok")
    error = payload.get("error")
    span.error = (error if isinstance(error, str) else json.dumps(error, default=str)) if error else None


def apply_span_events(spans: dict[str, RunSpan], events: list[RunEvent]) -> set[str]:
    """Fold ``span.start`` / ``span.end`` events into ``spans`` (by span id); the ids that changed. A ``span.end``
    with no ``span.start`` before it still creates the span, from the ``start_ts`` the end event repeats."""
    changed: set[str] = set()
    for event in events:
        if event.event not in SPAN_EVENTS or not event.span_id:
            continue
        span = _span_for_event(spans, event)
        if event.event in SPAN_START_EVENTS and not span.start_ts:
            span.start_ts = event.ts
        elif event.event in SPAN_END_EVENTS:
            _apply_span_end(span, event)
        changed.add(span.span_id)
    return changed


def build_span_tree(spans: list[RunSpan], events: list[RunEvent]) -> list[SpanTree]:
    """The forest of spans (a root is a span whose parent is unknown), each with its own events; children by start."""
    by_id = {s.span_id: s for s in spans}
    events_by_span: dict[str | None, list[RunEvent]] = {}
    for event in events:
        if event.event not in SPAN_EVENTS:
            events_by_span.setdefault(event.span_id, []).append(event)
    children_of: dict[str | None, list[RunSpan]] = {}
    for span in spans:
        parent = span.parent_span_id if span.parent_span_id in by_id else None
        children_of.setdefault(parent, []).append(span)
    for siblings in children_of.values():
        siblings.sort(key=lambda s: (s.start_ts or "", s.span_id))

    def node(span: RunSpan) -> SpanTree:
        return SpanTree(
            span=span,
            events=sorted(events_by_span.get(span.span_id, []), key=lambda e: (e.ts, e.source, e.seq)),
            children=[node(child) for child in children_of.get(span.span_id, [])],
        )

    return [node(root) for root in children_of.get(None, [])]


def newest_timestamp(events: list[RunEvent]) -> datetime.datetime | None:
    """The newest ``ts`` among ``events``, heartbeats included (they say the run is alive)."""
    stamps = [t for t in (parse_timestamp(e.ts) for e in events) if t is not None]
    return max(stamps) if stamps else None
