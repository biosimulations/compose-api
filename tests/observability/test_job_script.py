# ruff: noqa: E501  (a bash script with a long printf)
"""The sbatch script, run under bash with a fake ``singularity``: it records the job span and its events, hands the
trace context to the simulator through the env file, and records a failure with its exit code
(docs/plan-observability.md O2, O3)."""

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from compose_api.observability.events import RunSpan, apply_span_events, parse_complete_lines
from compose_api.observability.identity import job_span_id, trace_id_from_correlation
from compose_api.simulation.job_script import SimulationJob, simulation_job_script

CORRELATION = "simulation-abc1234"

# Stands in for `singularity run --compat --env-file F --bind HOST:/experiment IMAGE run ...`: reads the env file the
# way apptainer does, writes one engine event under the run's traceparent and one output file, then exits FAKE_EXIT.
FAKE_SINGULARITY = r"""#!/bin/bash
while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) set -a; . "$2"; set +a; shift 2 ;;
    --bind) HOST="${2%%:*}"; shift 2 ;;
    *) shift ;;
  esac
done
TRACE=$(echo "$PBG_TRACEPARENT" | cut -d- -f2); PARENT=$(echo "$PBG_TRACEPARENT" | cut -d- -f3)
SINK="${PBG_EVENT_SINKS#file:}"; SINK="$HOST${SINK#/experiment}"
printf '{"v":1,"ts":"2026-10-07T12:00:01.000Z","seq":1,"source":"node-42","component":"process_bigraph","event":"run.start","level":"info","trace_id":"%s","span_id":null,"parent_span_id":"%s","baggage":{"simulation_id":"%s"},"payload":{}}\n' "$TRACE" "$PARENT" "$PBG_TRACE_BAGGAGE" >> "$SINK"
echo result > "$HOST/output/out.txt"
if [ -n "${FAKE_BUNDLE:-}" ]; then  # a zarr store: a directory of chunk files, announced as one dataset
  mkdir -p "$HOST/output/run.fenics/u"; echo '{}' > "$HOST/output/run.fenics/.zattrs"; printf 'abcd' > "$HOST/output/run.fenics/u/0.0"
  chmod 600 "$HOST/output/run.fenics/.zattrs"  # as a mkstemp file renamed into place
fi
exit "${FAKE_EXIT:-0}"
"""


def _run(tmp_path: Path, exit_code: int, bundle: bool = False) -> tuple[subprocess.CompletedProcess[str], Path]:
    if shutil.which("zip") is None:
        pytest.skip("zip is not installed")
    experiment = tmp_path / "experiment-x"
    experiment.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "singularity"
    fake.write_text(FAKE_SINGULARITY)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    script = simulation_job_script(
        SimulationJob(
            job_name="x",
            experiment_id="x",
            simulation_id=7,
            correlation_id=CORRELATION,
            experiment_dir=str(experiment),
            container="image.sif",
            file_suffix="omex",
            output_dir="/experiment/output",
            end_time=1.0,
            log_file=str(tmp_path / "x.out"),
            is_batch=False,
            partition="p",
            qos="q",
        )
    )
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "SLURM_JOB_ID": "4242", "FAKE_EXIT": str(exit_code)}
    if bundle:
        env["FAKE_BUNDLE"] = "1"
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=False)  # noqa: S603, S607
    return result, experiment


def _read(path: Path) -> list:  # type: ignore[type-arg]
    events, _, bad = parse_complete_lines(path.read_bytes(), expected_trace_id=trace_id_from_correlation(CORRELATION))
    assert bad == 0
    return events


def test_a_successful_job_records_its_span_and_passes_the_trace_on(tmp_path: Path) -> None:
    result, experiment = _run(tmp_path, 0)
    assert result.returncode == 0, result.stderr
    job = _read(experiment / "events" / "job.jsonl")
    assert [e.event for e in job] == [
        "span.start",
        "job.start",
        "artifact.written",
        "artifact.written",
        "artifact.written",
        "job.end",
        "span.end",
    ]
    assert all(e.span_id == job_span_id(CORRELATION) and e.source == "job-4242" for e in job)
    assert [e.seq for e in job] == list(range(1, 8))  # the manifest loop must not run in a subshell
    artifacts = {e.payload["uri"]: e.payload for e in job if e.event == "artifact.written"}
    assert set(artifacts) == {"output/out.txt", "results.zip", "job.out"}
    assert artifacts["job.out"] == {"uri": "job.out", "kind": "log", "name": "SLURM log"}
    out = experiment / "output" / "out.txt"
    assert out.exists()  # output/ is kept: its files are datasets
    assert artifacts["output/out.txt"]["bytes"] == out.stat().st_size
    assert artifacts["output/out.txt"]["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert job[5].payload == {"exit_code": 0, "wall_s": job[5].payload["wall_s"]}
    spans: dict[str, RunSpan] = {}
    apply_span_events(spans, job)
    assert spans[job_span_id(CORRELATION)].status == "ok"

    (engine_file,) = (experiment / "events").glob("engine-*.jsonl")  # engine-{source}.jsonl
    engine = _read(engine_file)
    assert engine[0].parent_span_id == job_span_id(CORRELATION)
    assert engine[0].baggage == {"simulation_id": "simulation_id=7,experiment_id=x"}  # the fake echoes it raw
    assert (experiment / "results.zip").exists()


def test_a_zarr_store_is_announced_as_one_dataset(tmp_path: Path) -> None:
    result, experiment = _run(tmp_path, 0, bundle=True)
    assert result.returncode == 0, result.stderr
    job = _read(experiment / "events" / "job.jsonl")
    artifacts = {e.payload["uri"]: e.payload for e in job if e.event == "artifact.written"}
    assert set(artifacts) == {"output/out.txt", "output/run.fenics", "results.zip", "job.out"}
    bundle = artifacts["output/run.fenics"]
    assert "sha256" not in bundle
    assert bundle["bytes"] >= len("{}\n") + len("abcd")  # du counts blocks where -b is missing
    assert (experiment / "output" / "run.fenics" / ".zattrs").stat().st_mode & 0o044 == 0o044  # readable by the API


def test_a_failed_job_records_its_exit_code(tmp_path: Path) -> None:
    result, experiment = _run(tmp_path, 3)
    assert result.returncode == 3
    job = _read(experiment / "events" / "job.jsonl")
    # What the run wrote before failing is still announced; there is no archive.
    assert [e.event for e in job] == [
        "span.start",
        "job.start",
        "artifact.written",
        "artifact.written",
        "job.end",
        "span.end",
    ]
    assert [job[2].payload["uri"], job[3].payload["uri"]] == ["output/out.txt", "job.out"]
    assert job[4].level == "error" and job[4].payload["exit_code"] == 3
    spans: dict[str, RunSpan] = {}
    apply_span_events(spans, job)
    span = spans[job_span_id(CORRELATION)]
    assert span.status == "error" and span.error == "exit code 3"
    assert not (experiment / "results.zip").exists()
