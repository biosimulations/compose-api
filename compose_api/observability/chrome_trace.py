"""A run's spans and events as a Chrome Trace Event document, which opens in ui.perfetto.dev, speedscope or
chrome://tracing with no service and no upload.

Ported from viva-core (``viva_core/events/chrome_trace.py``) without its span groups: compose-api draws every span in
one process, packed into the fewest lanes that hold no overlap, so the lane count is the run's concurrency.

- Spans are "complete" events (``ph: "X"``); other events are instants (``ph: "i"``) in their own process.
- Timestamps are microseconds since the earliest span or event, so every trace starts at zero.
- A span still open is drawn to the run's latest end (or "now" for a live run) and says ``still_open``. One the
  ingester closed at the run's end says ``end_not_recorded``. ``end_recorded`` is on every span.
"""

import datetime
from collections.abc import Sequence
from typing import Required, TypedDict

from compose_api.observability.events import (
    SPAN_END_EVENTS,
    SPAN_EVENTS,
    SPAN_START_EVENTS,
    UNENDED_SPAN_STATUS,
    RunEvent,
    RunSpan,
)

_US = 1_000_000
_SPANS_PID, _EVENTS_PID = 1, 2


class TraceEvent(TypedDict, total=False):
    ph: Required[str]
    pid: Required[int]
    tid: Required[int]
    name: str
    cat: str
    ts: int
    dur: int
    s: str
    args: dict[str, object]


class TraceDocument(TypedDict):
    traceEvents: list[TraceEvent]
    displayTimeUnit: str
    otherData: dict[str, str]


def _posix(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)).timestamp()


def _iso(timestamp: float) -> str:
    return datetime.datetime.fromtimestamp(timestamp, tz=datetime.UTC).isoformat(timespec="milliseconds")[:-6] + "Z"


def _lanes(intervals: list[tuple[float, float, str]]) -> dict[str, int]:
    """Greedy interval partitioning: a span takes the first lane whose last occupant has ended."""
    free_at: list[float] = []
    lane: dict[str, int] = {}
    for begin, end, span_id in sorted(intervals):
        index = next((i for i, t in enumerate(free_at) if t <= begin), None)
        if index is None:
            free_at.append(end)
            index = len(free_at) - 1
        else:
            free_at[index] = end
        lane[span_id] = index + 1
    return lane


def _span_args(span: RunSpan, origin: RunEvent | None, *, open_ended: bool) -> dict[str, object]:
    args: dict[str, object] = {"span_id": span.span_id, **(span.attrs or {})}
    if span.parent_span_id:
        args["parent_span_id"] = span.parent_span_id
    if span.status:
        args["status"] = span.status
    if span.error:
        args["error"] = span.error
    if origin is not None:
        args["source"] = origin.source
        if origin.baggage:
            args["baggage"] = dict(origin.baggage)
    args["end_recorded"] = not open_ended and span.status != UNENDED_SPAN_STATUS
    if open_ended:
        args["still_open"] = True
    elif span.status == UNENDED_SPAN_STATUS:
        args["end_not_recorded"] = True
    return args


def _event_args(event: RunEvent) -> dict[str, object]:
    args: dict[str, object] = {"level": event.level, **(event.payload or {})}
    if event.baggage:
        args["baggage"] = dict(event.baggage)
    if event.tags:
        args["tags"] = dict(event.tags)
    identity = {
        "source": event.source,
        "seq": event.seq,
        "span_id": event.span_id,
        "global_time": event.global_time,
        "wall_time": event.wall_time,
    }
    args["event"] = {k: v for k, v in identity.items() if v is not None}
    return args


def _span_records(events: Sequence[RunEvent]) -> dict[str, RunEvent]:
    """Each span's own record, by span id: its first ``span.start``, else its first ``span.end``."""
    starts: dict[str, RunEvent] = {}
    ends: dict[str, RunEvent] = {}
    for record in events:
        if record.span_id and record.event in SPAN_START_EVENTS:
            starts.setdefault(record.span_id, record)
        elif record.span_id and record.event in SPAN_END_EVENTS:
            ends.setdefault(record.span_id, record)
    return {**ends, **starts}


def _instant(event: RunEvent, origin: float) -> TraceEvent:
    return {
        "ph": "i",
        "s": "t",
        "name": event.event,
        "cat": event.component,
        "pid": _EVENTS_PID,
        "tid": 0,
        "ts": round(((_posix(event.ts) or origin) - origin) * _US),
        "args": _event_args(event),
    }


def chrome_trace_document(
    spans: Sequence[RunSpan],
    events: Sequence[RunEvent],
    *,
    trace_id: str | None,
    other_data: dict[str, str] | None = None,
    live: bool = False,
    now: float | None = None,
) -> TraceDocument:
    """The document for a run: its spans and its non-span events. ``live``: draw open spans to ``now`` (default: the
    wall clock) rather than to the latest recorded end."""
    other: dict[str, str] = {"source": "compose-api", **({"trace_id": trace_id} if trace_id else {})}
    other.update(other_data or {})
    instants = [e for e in events if e.event not in SPAN_EVENTS]
    starts = [t for t in (_posix(s.start_ts) for s in spans) if t is not None]
    starts += [t for t in (_posix(e.ts) for e in instants) if t is not None]
    if not starts:
        return {"traceEvents": [], "displayTimeUnit": "ms", "otherData": other}
    origin = min(starts)
    if live:
        other["live"] = "true"
        now = now if now is not None else datetime.datetime.now(tz=datetime.UTC).timestamp()
    ends = [t for t in (_posix(s.end_ts) for s in spans) if t is not None]
    wall_now = now if now is not None else max(ends or [origin])
    other["start_ts"], other["end_ts"] = _iso(origin), _iso(wall_now)

    records = _span_records(events)

    drawn: list[tuple[RunSpan, float, float, bool]] = []
    for span in spans:
        begin = _posix(span.start_ts)
        if begin is None:
            continue
        end = _posix(span.end_ts)
        drawn.append((span, begin, max(wall_now, begin) if end is None else end, end is None))
    lanes = _lanes([(begin, end, span.span_id) for span, begin, end, _ in drawn])

    out: list[TraceEvent] = [
        {"ph": "M", "pid": _SPANS_PID, "tid": 0, "name": "process_name", "args": {"name": "spans"}},
        {"ph": "M", "pid": _EVENTS_PID, "tid": 0, "name": "process_name", "args": {"name": "events"}},
    ]
    for span, begin, end, open_ended in drawn:
        out.append({
            "ph": "X",
            "name": span.name,
            "cat": span.name,
            "pid": _SPANS_PID,
            "tid": lanes[span.span_id],
            "ts": round((begin - origin) * _US),
            "dur": max(1, round((end - begin) * _US)),
            "args": _span_args(span, records.get(span.span_id), open_ended=open_ended),
        })
    out.extend(_instant(event, origin) for event in instants if _posix(event.ts) is not None)
    out.sort(key=lambda r: (r.get("ts", 0), r["ph"]))
    return {"traceEvents": out, "displayTimeUnit": "ms", "otherData": other}
