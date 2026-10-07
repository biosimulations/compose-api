from compose_api.observability.identity import job_span_id, parse_traceparent, trace_id_from_correlation, traceparent


def test_trace_identity_is_derived_and_well_formed() -> None:
    trace_id, span_id = trace_id_from_correlation("simulation-abc1234"), job_span_id("simulation-abc1234")
    assert len(trace_id) == 32 and len(span_id) == 16 and int(trace_id, 16) and int(span_id, 16)
    assert trace_id == trace_id_from_correlation("simulation-abc1234") != trace_id_from_correlation("simulation-x")
    header = traceparent(trace_id, span_id)
    assert header == f"00-{trace_id}-{span_id}-01"
    assert parse_traceparent(header) == (trace_id, span_id)
    assert parse_traceparent("00-xyz-01") is None
