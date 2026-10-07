"""A run's events and spans (docs/plan-observability.md O4). Rows carry no owner: they reach their simulation through
``hpcrun`` (O7)."""

import datetime
import uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from compose_api.db.db_utils import DeclarativeTableBase
from compose_api.observability.datasets import Dataset, DatasetRow
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


class ORMDataset(DeclarativeTableBase):
    """A file a run produced (docs/plan-observability.md O5, O6). Readable by whoever may read its simulation (O7)."""

    __tablename__ = "dataset"
    __table_args__ = (UniqueConstraint("simulation_id", "path", name="uq_dataset_simulation_path"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    simulation_id: Mapped[int] = mapped_column(
        ForeignKey("simulation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hpcrun_id: Mapped[int | None] = mapped_column(ForeignKey("hpcrun.id", ondelete="SET NULL"), nullable=True)
    path: Mapped[str] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(nullable=False, index=True)
    media_type: Mapped[str] = mapped_column(nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attributes: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    origin: Mapped[str] = mapped_column(nullable=False)
    span_id: Mapped[str | None] = mapped_column(nullable=True)
    available: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def to_row(self) -> DatasetRow:
        return DatasetRow(
            path=self.path,
            origin=self.origin,
            kind=self.kind,
            media_type=self.media_type,
            display_name=self.display_name,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
            attributes=dict(self.attributes or {}),
            span_id=self.span_id,
            available=self.available,
        )

    def to_dataset(self) -> Dataset:
        return Dataset(
            id=str(self.id),
            simulation_id=self.simulation_id,
            path=self.path,
            kind=self.kind,
            media_type=self.media_type,
            display_name=self.display_name,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
            attributes=dict(self.attributes or {}),
            origin=self.origin,
            span_id=self.span_id,
            available=self.available,
            created_at=_iso(self.created_at),
            updated_at=_iso(self.updated_at),
        )
