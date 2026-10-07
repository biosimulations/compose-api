"""A run's events and spans (docs/plan-observability.md O4). Rows carry no owner: they reach their simulation through
``hpcrun`` (O7)."""

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from compose_api.db.db_utils import DeclarativeTableBase
from compose_api.observability.events import RunEvent, RunSpan


def _iso(value: datetime.datetime | None) -> str | None:
    """A stored timestamp as the engine writes one: ISO 8601 UTC with milliseconds and ``Z``."""
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=datetime.UTC)
    return aware.astimezone(datetime.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ORMRunEvent(DeclarativeTableBase):
    __tablename__ = "run_event"
    __table_args__ = (
        UniqueConstraint("trace_id", "source", "seq", name="uq_run_event_trace_source_seq"),
        Index("ix_run_event_hpcrun_id_id", "hpcrun_id", "id"),
        Index("ix_run_event_trace_span", "trace_id", "span_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hpcrun_id: Mapped[int] = mapped_column(ForeignKey("hpcrun.id", ondelete="CASCADE"), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)  # the API's are microsecond timestamps
    ts: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    component: Mapped[str] = mapped_column(nullable=False)
    event: Mapped[str] = mapped_column(nullable=False, index=True)
    level: Mapped[str] = mapped_column(nullable=False, server_default="info")
    global_time: Mapped[float | None] = mapped_column(nullable=True)
    wall_time: Mapped[float | None] = mapped_column(nullable=True)
    span_id: Mapped[str | None] = mapped_column(nullable=True)
    parent_span_id: Mapped[str | None] = mapped_column(nullable=True)
    baggage: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    def to_run_event(self) -> RunEvent:
        return RunEvent(
            cursor=self.id,
            seq=self.seq,
            source=self.source,
            ts=_iso(self.ts) or "",
            component=self.component,
            event=self.event,
            level=self.level,
            baggage=self.baggage,
            global_time=self.global_time,
            wall_time=self.wall_time,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            payload=self.payload,
            tags=self.tags,
        )


class ORMRunSpan(DeclarativeTableBase):
    __tablename__ = "run_span"
    __table_args__ = (UniqueConstraint("trace_id", "span_id", name="uq_run_span_trace_span"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hpcrun_id: Mapped[int] = mapped_column(ForeignKey("hpcrun.id", ondelete="CASCADE"), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    span_id: Mapped[str] = mapped_column(nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(nullable=True)
    name: Mapped[str] = mapped_column(nullable=False)
    attrs: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    start_ts: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_ts: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(nullable=True)
    status: Mapped[str | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(nullable=True)

    def to_run_span(self) -> RunSpan:
        return RunSpan(
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            name=self.name,
            attrs=self.attrs,
            start_ts=_iso(self.start_ts),
            end_ts=_iso(self.end_ts),
            duration_s=self.duration_s,
            status=self.status,
            error=self.error,
        )
