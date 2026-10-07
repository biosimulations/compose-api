"""Events the API writes about a run itself: dispatch and SLURM transitions (docs/plan-observability.md O3).

They go straight to ``run_event`` with ``source="api"``, so every run has a trace even when its simulator emits
nothing. They hang from the run's job span, the root the job script and the engine use too.
"""

import datetime
import logging
import time

from compose_api.db.database_service import DatabaseService
from compose_api.observability.events import RunEvent
from compose_api.observability.identity import job_span_id
from compose_api.simulation.models import HpcRun

logger = logging.getLogger(__name__)

API_SOURCE = "api"
API_COMPONENT = "compose_api.api"


def _now() -> str:
    return datetime.datetime.now(tz=datetime.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def record_api_event(
    database_service: DatabaseService,
    run: HpcRun,
    event: str,
    payload: dict[str, object],
    level: str = "info",
    ts: str | None = None,
) -> None:
    """Store one API event for ``run``. Never raises: losing an event must not fail a dispatch or a status poll."""
    if run.trace_id is None:
        return
    try:
        record = RunEvent(
            seq=time.time_ns() // 1000,  # unique per source "api" within a trace, and in time order
            source=API_SOURCE,
            ts=ts or _now(),
            component=API_COMPONENT,
            event=event,
            level=level,
            span_id=job_span_id(run.correlation_id),
            payload=payload,
        )
        await database_service.get_events_db().insert_events(run.database_id, run.trace_id, [record])
    except Exception:
        logger.exception(f"Could not record {event} for hpcrun {run.database_id}")
