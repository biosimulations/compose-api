"""Tail each running simulation's ``events/*.jsonl`` on the mounted store into ``run_event`` / ``run_span``
(docs/plan-observability.md O4).

The rules follow viva-core's ingester (``viva_core/events/ingest.py``), with a mounted directory in place of an object
listing:

- **A byte cursor per file**, kept in ``hpcrun.events_cursor``, and only complete lines are consumed, so a writer
  that is mid-line is read on the next pass.
- **Idempotent.** Events are deduplicated on ``(trace_id, source, seq)``, so rereading a file after a crash between
  the insert and the cursor save is harmless.
- **Bounded.** Each file gives at most ``max_bytes`` per pass; heartbeats and ``debug`` events are folded but not
  stored.
- **Datasets ride the same stream.** ``artifact.written`` events, from the job script's manifest or from the
  simulator, are registered as datasets (``observability.datasets``).
- **A grace window after the run ends.** A shared filesystem shows a job's last writes late, so the ingester keeps
  reading for ``grace_s`` after it first sees the run terminal, then closes any span still open as ``unknown`` and
  stops.
"""

import asyncio
import datetime
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from compose_api.db.database_service import DatabaseService
from compose_api.db.services.events_db import DONE_KEY, TERMINAL_SEEN_KEY, IngestCandidate
from compose_api.observability.datasets import artifact_records
from compose_api.observability.events import (
    UNENDED_SPAN_STATUS,
    RunEvent,
    apply_span_events,
    newest_timestamp,
    parse_complete_lines,
    storable_events,
)

logger = logging.getLogger(__name__)

EVENTS_DIR = "events"


@dataclass
class _Read:
    events: list[RunEvent]
    cursor: dict[str, int]
    bad_lines: int


def _read_new(events_dir: Path, cursor: dict[str, int], trace_id: str, max_bytes: int) -> _Read:
    """Every complete new line of every ``*.jsonl`` in ``events_dir``, and the advanced cursor. Blocking I/O."""
    cursor = dict(cursor)
    events: list[RunEvent] = []
    bad = 0
    if not events_dir.is_dir():
        return _Read(events, cursor, bad)
    for path in sorted(events_dir.glob("*.jsonl")):
        offset = cursor.get(path.name, 0)
        try:
            if path.stat().st_size <= offset:
                continue
            with path.open("rb") as handle:
                handle.seek(offset)
                data = handle.read(max_bytes)
        except OSError:
            logger.warning(f"Could not read {path}", exc_info=True)
            continue
        parsed, consumed, skipped = parse_complete_lines(data, expected_trace_id=trace_id)
        if consumed == 0 and len(data) >= max_bytes:
            consumed = len(data)  # one line longer than a whole read: skip it rather than stall on it forever
            skipped += 1
        cursor[path.name] = offset + consumed
        events.extend(parsed)
        bad += skipped
    return _Read(events, cursor, bad)


def _exit_code(events: list[RunEvent]) -> int | None:
    for event in reversed(events):
        if event.event == "job.end" and event.payload and isinstance(event.payload.get("exit_code"), int):
            code = event.payload["exit_code"]
            return code if isinstance(code, int) else None
    return None


class EventIngester:
    def __init__(
        self,
        database_service: DatabaseService,
        experiment_dir: Callable[[str], Path],
        grace_s: float = 300.0,
        max_bytes: int = 8 * 1024 * 1024,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.database_service = database_service
        self.experiment_dir = experiment_dir
        self.grace_s = grace_s
        self.max_bytes = max_bytes
        self.clock = clock

    async def ingest_once(self) -> int:
        """One pass over every run the ingester has not finished with; the number of events stored."""
        stored = 0
        for candidate in await self.database_service.get_events_db().ingest_candidates():
            try:
                stored += await self.ingest_run(candidate)
            except Exception:
                logger.exception(f"Event ingest failed for hpcrun {candidate.hpcrun_id}")
        return stored

    async def ingest_run(self, run: IngestCandidate) -> int:
        events_db = self.database_service.get_events_db()
        events_dir = self.experiment_dir(run.experiment_id) / EVENTS_DIR
        read = await asyncio.to_thread(_read_new, events_dir, run.cursor, run.trace_id, self.max_bytes)
        if read.bad_lines:
            logger.warning(f"hpcrun {run.hpcrun_id}: skipped {read.bad_lines} unusable event lines")
        stored = 0
        last_event_at: datetime.datetime | None = None
        if read.events:
            stored = await events_db.insert_events(run.hpcrun_id, run.trace_id, storable_events(read.events))
            spans = await events_db.get_spans(run.trace_id)
            changed = apply_span_events(spans, read.events)
            await events_db.upsert_spans(run.hpcrun_id, run.trace_id, [spans[i] for i in sorted(changed)])
            # Before the cursor is saved: if registering fails, the next pass rereads these events (inserts are
            # idempotent and registration merges), so no artifact is lost.
            await self.database_service.get_datasets_db().register(
                run.simulation_id, run.hpcrun_id, artifact_records(read.events)
            )
            last_event_at = newest_timestamp(read.events)

        cursor = read.cursor
        if run.terminal:
            now = self.clock()
            seen = cursor.setdefault(TERMINAL_SEEN_KEY, int(now))
            if not read.events and now - seen >= self.grace_s:
                await self._close_open_spans(run)
                cursor[DONE_KEY] = 1
        if cursor != run.cursor or read.events:
            await events_db.save_ingest_state(
                run.hpcrun_id, cursor, last_event_at=last_event_at, exit_code=_exit_code(read.events)
            )
        return stored

    async def _close_open_spans(self, run: IngestCandidate) -> None:
        events_db = self.database_service.get_events_db()
        spans = await events_db.get_spans(run.trace_id)
        now = datetime.datetime.now(tz=datetime.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        unended = [s for s in spans.values() if s.end_ts is None]
        for span in unended:
            span.end_ts, span.duration_s, span.status = now, None, UNENDED_SPAN_STATUS
        await events_db.upsert_spans(run.hpcrun_id, run.trace_id, unended)
