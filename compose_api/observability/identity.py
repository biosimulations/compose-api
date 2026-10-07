"""A run's trace identity, derived from its correlation id (plan-observability O1).

The job script carries the trace context to the simulator, and it is written before the ``hpcrun`` row exists. Deriving
the ids from the correlation id means both sides compute the same ids, with nothing stored between submit and insert.
Ported from viva-core (``viva_core/events/events_env.py``: ``trace_id_from_correlation``, ``campaign_span_id``,
``traceparent``).
"""

import hashlib
import re

_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")


def trace_id_from_correlation(correlation_id: str) -> str:
    """The run's W3C trace id: 32 lowercase hex characters."""
    return hashlib.sha256(correlation_id.encode("utf-8")).hexdigest()[:32]


def job_span_id(correlation_id: str) -> str:
    """The id of the span that covers the whole job, the root every other span of the run hangs from."""
    return hashlib.sha256(f"job:{correlation_id}".encode()).hexdigest()[:16]


def traceparent(trace_id: str, span_id: str) -> str:
    """A W3C ``traceparent`` header value (version 00, sampled)."""
    return f"00-{trace_id}-{span_id}-01"


def parse_traceparent(value: str) -> tuple[str, str] | None:
    """``(trace_id, span_id)`` from a ``traceparent``, or None if it is malformed."""
    m = _TRACEPARENT.match(value.strip())
    return (m.group(1), m.group(2)) if m else None
