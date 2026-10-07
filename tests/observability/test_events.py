"""The pure half of event handling: parsing JSON lines, what is stored, folding spans, the span tree and the Chrome
Trace document (docs/plan-observability.md O4)."""

import json

from compose_api.observability.chrome_trace import chrome_trace_document
from compose_api.observability.events import (
    RunEvent,
    RunSpan,
    apply_span_events,
    build_span_tree,
    parse_complete_lines,
    storable_events,
)

TRACE = "a" * 32
JOB, TASK = "1" * 16, "2" * 16


def line(
    seq: int,
    event: str,
    *,
    span: str | None = JOB,
    parent: str | None = None,
    level: str = "info",
    ts: str = "2026-10-07T12:00:00.000Z",
    trace: str = TRACE,
    **payload: object,
) -> str:
    record = {
        "v": 1,
        "ts": ts,
        "seq": seq,
        "source": "job-1",
        "component": "compose_api.job",
        "event": event,
        "level": level,
        "trace_id": trace,
        "span_id": span,
        "parent_span_id": parent,
        "payload": payload,
    }
    return json.dumps(record) + "\n"


def test_only_complete_lines_are_consumed() -> None:
    whole = line(1, "job.start") + line(2, "tick")
    events, consumed, bad = parse_complete_lines((whole + '{"v":1,"seq":3,').encode())
    assert [e.seq for e in events] == [1, 2] and consumed == len(whole.encode()) and bad == 0


def test_unusable_lines_and_other_traces_are_skipped() -> None:
    data = (line(1, "job.start") + "not json\n" + '{"seq": 2}\n' + line(3, "x", trace="b" * 32)).encode()
    events, consumed, bad = parse_complete_lines(data, expected_trace_id=TRACE)
    assert [e.seq for e in events] == [1] and bad == 3 and consumed == len(data)


def test_heartbeats_and_debug_are_not_stored() -> None:
    events, _, _ = parse_complete_lines((line(1, "tick") + line(2, "x", level="debug") + line(3, "run.end")).encode())
    assert [e.event for e in storable_events(events)] == ["run.end"]


def _events(*lines: str) -> list[RunEvent]:
    return parse_complete_lines("".join(lines).encode())[0]


def test_spans_fold_from_start_and_end_and_nest() -> None:
    spans: dict[str, RunSpan] = {}
    changed = apply_span_events(
        spans,
        _events(
            line(1, "span.start", name="job", attrs={"host": "n1"}, start_ts="2026-10-07T12:00:00.000Z"),
            line(2, "span.start", span=TASK, parent=JOB, name="task", start_ts="2026-10-07T12:00:01.000Z"),
            line(3, "run.start", span=TASK, parent=JOB),
            line(
                4,
                "span.end",
                span=TASK,
                parent=JOB,
                name="task",
                status="ok",
                duration_s=2.0,
                end_ts="2026-10-07T12:00:03.000Z",
            ),
        ),
    )
    assert changed == {JOB, TASK}
    assert spans[JOB].end_ts is None and spans[JOB].attrs == {"host": "n1"}
    assert spans[TASK].status == "ok" and spans[TASK].duration_s == 2.0 and spans[TASK].parent_span_id == JOB

    tree = build_span_tree(list(spans.values()), _events(line(3, "run.start", span=TASK, parent=JOB)))
    assert [t.span.name for t in tree] == ["job"]
    assert [c.span.name for c in tree[0].children] == ["task"]
    assert [e.event for e in tree[0].children[0].events] == ["run.start"]


def test_an_end_without_a_start_still_makes_a_span() -> None:
    spans: dict[str, RunSpan] = {}
    apply_span_events(
        spans,
        _events(
            line(1, "span.end", level="error", name="job", start_ts="2026-10-07T12:00:00.000Z", error="exit code 1")
        ),
    )
    assert spans[JOB].start_ts == "2026-10-07T12:00:00.000Z"
    assert spans[JOB].status == "error" and spans[JOB].error == "exit code 1"


def test_chrome_trace_draws_spans_in_lanes_and_events_as_instants() -> None:
    spans = [
        RunSpan(
            span_id=JOB, name="job", start_ts="2026-10-07T12:00:00.000Z", end_ts="2026-10-07T12:00:10.000Z", status="ok"
        ),
        RunSpan(span_id=TASK, parent_span_id=JOB, name="task", start_ts="2026-10-07T12:00:01.000Z"),  # still open
    ]
    events = _events(line(5, "job.end", ts="2026-10-07T12:00:10.000Z", exit_code=0))
    doc = chrome_trace_document(spans, events, trace_id=TRACE)
    complete = {r["name"]: r for r in doc["traceEvents"] if r["ph"] == "X"}
    assert complete["job"]["ts"] == 0 and complete["job"]["dur"] == 10_000_000
    assert complete["task"]["tid"] != complete["job"]["tid"]  # they overlap, so two lanes
    assert complete["task"]["args"]["still_open"] is True and complete["job"]["args"]["end_recorded"] is True
    assert [r["name"] for r in doc["traceEvents"] if r["ph"] == "i"] == ["job.end"]
    assert doc["otherData"]["trace_id"] == TRACE
    assert chrome_trace_document([], [], trace_id=None)["traceEvents"] == []
