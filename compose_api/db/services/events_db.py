"""Storage for a run's events and spans, and the ingester's bookkeeping on ``hpcrun``.

See docs/plan-observability.md (O4).
"""

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import override

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from compose_api.db.tables.hpc_tables import TERMINAL_JOB_STATUSES, JobTypeDB, ORMHpcRun
from compose_api.db.tables.observability_tables import ORMRunEvent, ORMRunSpan
from compose_api.db.tables.simulator_tables import ORMSimulation
from compose_api.observability.events import RunEvent, RunSpan, parse_timestamp

#: ``hpcrun.events_cursor`` keys that are not file names: when the ingester first saw the run ended (epoch seconds),
#: and that it has finished with the run.
TERMINAL_SEEN_KEY = "__terminal_seen__"
DONE_KEY = "__done__"


@dataclass(frozen=True)
class IngestCandidate:
    hpcrun_id: int
    trace_id: str
    simulation_id: int
    experiment_id: str
    terminal: bool
    cursor: dict[str, int]


@dataclass(frozen=True)
class RunTraceRef:
    """The run behind a simulation, as the events routes need it."""

    hpcrun_id: int
    trace_id: str | None
    terminal: bool


class EventsDatabaseService(ABC):
    @abstractmethod
    async def insert_events(self, hpcrun_id: int, trace_id: str, events: list[RunEvent]) -> int:
        """Insert ``events``, skipping any already stored (same trace, source and seq); the number inserted."""

    @abstractmethod
    async def get_spans(self, trace_id: str) -> dict[str, RunSpan]:
        pass

    @abstractmethod
    async def upsert_spans(self, hpcrun_id: int, trace_id: str, spans: list[RunSpan]) -> None:
        pass

    @abstractmethod
    async def list_events(
        self,
        trace_id: str,
        after: int | None = None,
        limit: int = 500,
        level: str | None = None,
        event: str | None = None,
        span_id: str | None = None,
    ) -> list[RunEvent]:
        """Stored events in insertion order, those with a cursor greater than ``after``."""

    @abstractmethod
    async def count_events(self, trace_id: str) -> int:
        pass

    @abstractmethod
    async def ingest_candidates(self) -> list[IngestCandidate]:
        """Simulation runs the ingester has not finished with."""

    @abstractmethod
    async def save_ingest_state(
        self,
        hpcrun_id: int,
        cursor: dict[str, int],
        last_event_at: datetime.datetime | None = None,
        exit_code: int | None = None,
    ) -> None:
        pass

    @abstractmethod
    async def get_run_for_simulation(self, simulation_id: int) -> RunTraceRef | None:
        pass


class EventsORMExecutor(EventsDatabaseService):
    def __init__(self, async_session_maker: async_sessionmaker[AsyncSession]):
        self.async_session_maker = async_session_maker

    @override
    async def insert_events(self, hpcrun_id: int, trace_id: str, events: list[RunEvent]) -> int:
        if not events:
            return 0
        rows = [
            {
                "hpcrun_id": hpcrun_id,
                "trace_id": trace_id,
                "source": e.source,
                "seq": e.seq,
                "ts": parse_timestamp(e.ts),
                "component": e.component,
                "event": e.event,
                "level": e.level,
                "global_time": e.global_time,
                "wall_time": e.wall_time,
                "span_id": e.span_id,
                "parent_span_id": e.parent_span_id,
                "baggage": e.baggage,
                "payload": e.payload,
                "tags": e.tags,
            }
            for e in events
        ]
        inserted = 0
        async with self.async_session_maker() as session, session.begin():
            for start in range(0, len(rows), 1000):  # asyncpg allows 32,767 parameters per statement
                stmt = (
                    insert(ORMRunEvent)
                    .values(rows[start : start + 1000])
                    .on_conflict_do_nothing(constraint="uq_run_event_trace_source_seq")
                    .returning(ORMRunEvent.id)
                )
                inserted += len((await session.execute(stmt)).all())
        return inserted

    @override
    async def get_spans(self, trace_id: str) -> dict[str, RunSpan]:
        async with self.async_session_maker() as session:
            result = await session.execute(select(ORMRunSpan).where(ORMRunSpan.trace_id == trace_id))
            return {row.span_id: row.to_run_span() for row in result.scalars().all()}

    @override
    async def upsert_spans(self, hpcrun_id: int, trace_id: str, spans: list[RunSpan]) -> None:
        if not spans:
            return
        async with self.async_session_maker() as session, session.begin():
            for span in spans:
                values = {
                    "parent_span_id": span.parent_span_id,
                    "name": span.name,
                    "attrs": span.attrs,
                    "start_ts": parse_timestamp(span.start_ts),
                    "end_ts": parse_timestamp(span.end_ts),
                    "duration_s": span.duration_s,
                    "status": span.status,
                    "error": span.error,
                }
                stmt = insert(ORMRunSpan).values(hpcrun_id=hpcrun_id, trace_id=trace_id, span_id=span.span_id, **values)
                await session.execute(stmt.on_conflict_do_update(constraint="uq_run_span_trace_span", set_=values))

    @override
    async def list_events(
        self,
        trace_id: str,
        after: int | None = None,
        limit: int = 500,
        level: str | None = None,
        event: str | None = None,
        span_id: str | None = None,
    ) -> list[RunEvent]:
        stmt = select(ORMRunEvent).where(ORMRunEvent.trace_id == trace_id)
        if after is not None:
            stmt = stmt.where(ORMRunEvent.id > after)
        if level is not None:
            stmt = stmt.where(ORMRunEvent.level == level)
        if event is not None:
            stmt = stmt.where(ORMRunEvent.event == event)
        if span_id is not None:
            stmt = stmt.where(ORMRunEvent.span_id == span_id)
        async with self.async_session_maker() as session:
            result = await session.execute(stmt.order_by(ORMRunEvent.id).limit(limit))
            return [row.to_run_event() for row in result.scalars().all()]

    @override
    async def count_events(self, trace_id: str) -> int:
        async with self.async_session_maker() as session:
            stmt = select(func.count()).where(ORMRunEvent.trace_id == trace_id)
            return int((await session.execute(stmt)).scalar_one())

    @override
    async def ingest_candidates(self) -> list[IngestCandidate]:
        stmt = (
            select(ORMHpcRun, ORMSimulation.experiment_id)
            .join(ORMSimulation, ORMSimulation.id == ORMHpcRun.simulation_id)
            .where(
                ORMHpcRun.job_type == JobTypeDB.SIMULATION,
                ORMHpcRun.trace_id.is_not(None),
                ~ORMHpcRun.events_cursor.has_key(DONE_KEY),
            )
        )
        async with self.async_session_maker() as session:
            rows = (await session.execute(stmt)).all()
        return [
            IngestCandidate(
                hpcrun_id=run.id,
                trace_id=run.trace_id or "",
                simulation_id=run.simulation_id or 0,
                experiment_id=experiment_id,
                terminal=run.status in TERMINAL_JOB_STATUSES,
                cursor=dict(run.events_cursor or {}),
            )
            for run, experiment_id in rows
        ]

    @override
    async def save_ingest_state(
        self,
        hpcrun_id: int,
        cursor: dict[str, int],
        last_event_at: datetime.datetime | None = None,
        exit_code: int | None = None,
    ) -> None:
        values: dict[str, object] = {"events_cursor": cursor}
        if last_event_at is not None:
            values["last_event_at"] = last_event_at
        if exit_code is not None:
            values["exit_code"] = exit_code
        async with self.async_session_maker() as session, session.begin():
            await session.execute(update(ORMHpcRun).where(ORMHpcRun.id == hpcrun_id).values(**values))

    @override
    async def get_run_for_simulation(self, simulation_id: int) -> RunTraceRef | None:
        stmt = (
            select(ORMHpcRun)
            .where(ORMHpcRun.simulation_id == simulation_id, ORMHpcRun.job_type == JobTypeDB.SIMULATION)
            .order_by(ORMHpcRun.id.desc())
            .limit(1)
        )
        async with self.async_session_maker() as session:
            run = (await session.execute(stmt)).scalars().one_or_none()
        if run is None:
            return None
        return RunTraceRef(hpcrun_id=run.id, trace_id=run.trace_id, terminal=run.status in TERMINAL_JOB_STATUSES)
