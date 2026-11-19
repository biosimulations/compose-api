# ruff: noqa: E501  (a bash script with a long printf)
"""The sbatch script, run under bash with a fake ``singularity``: it records the job span and its events, hands the
trace context to the simulator through the env file, and records a failure with its exit code
(docs/plan-observability.md O2, O3)."""

import contextlib
import hashlib
import os
import shutil
import signal
import stat
import subprocess
import time
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
if [ -n "${FAKE_IGNORE_TERM:-}" ]; then  # hung, and deaf to SIGTERM, as on a bad node: only SIGKILL ends it
  trap '' TERM; sleep 60
fi
exit "${FAKE_EXIT:-0}"
"""


INPUT = b"PK\x03\x04 a COMBINE archive"


def _job(tmp_path: Path, exit_code: int, staged_input: bool = True) -> tuple[str, dict[str, str], Path]:
    """The script, its environment (the fake singularity first on PATH) and the experiment directory."""
    if shutil.which("zip") is None:
        pytest.skip("zip is not installed")
    experiment = tmp_path / "experiment-x"
    experiment.mkdir()
    if staged_input:
        (experiment / "x.omex").write_bytes(INPUT)  # where submit_simulation_job copies the request's file
        (experiment / "x.omex").chmod(0o600)  # as uploaded: scp keeps the mode of the API's NamedTemporaryFile
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
    return script, env, experiment


def _run(
    tmp_path: Path, exit_code: int, bundle: bool = False, staged_input: bool = True
) -> tuple[subprocess.CompletedProcess[str], Path]:
    script, env, experiment = _job(tmp_path, exit_code, staged_input)
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
        "artifact.written",  # the input, before the simulator runs
        "artifact.written",
        "artifact.written",
        "artifact.written",
        "job.end",
        "span.end",
    ]
    assert all(e.span_id == job_span_id(CORRELATION) and e.source == "job-4242" for e in job)
    assert [e.seq for e in job] == list(range(1, 9))  # the manifest loop must not run in a subshell
    artifacts = {e.payload["uri"]: e.payload for e in job if e.event == "artifact.written"}
    assert set(artifacts) == {"x.omex", "output/out.txt", "results.zip", "job.out"}
    assert artifacts["job.out"] == {"uri": "job.out", "kind": "log", "name": "SLURM log"}
    assert artifacts["x.omex"] == {
        "uri": "x.omex",
        "kind": "input",
        "name": "Simulation input",
        "bytes": len(INPUT),
        "sha256": hashlib.sha256(INPUT).hexdigest(),
        "attributes": {"file_type": "omex", "end_time": 1.0, "batch": False},
    }
    assert (experiment / "x.omex").stat().st_mode & 0o044 == 0o044  # readable by the API
    out = experiment / "output" / "out.txt"
    assert out.exists()  # output/ is kept: its files are datasets
    assert artifacts["output/out.txt"]["bytes"] == out.stat().st_size
    assert artifacts["output/out.txt"]["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert job[6].payload == {"exit_code": 0, "wall_s": job[6].payload["wall_s"]}
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
    assert set(artifacts) == {"x.omex", "output/out.txt", "output/run.fenics", "results.zip", "job.out"}
    bundle = artifacts["output/run.fenics"]
    assert "sha256" not in bundle
    assert bundle["bytes"] >= len("{}\n") + len("abcd")  # du counts blocks where -b is missing
    assert (experiment / "output" / "run.fenics" / ".zattrs").stat().st_mode & 0o044 == 0o044  # readable by the API


def test_a_job_without_its_input_announces_none(tmp_path: Path) -> None:
    result, experiment = _run(tmp_path, 0, staged_input=False)
    assert result.returncode == 0, result.stderr
    artifacts = [e.payload for e in _read(experiment / "events" / "job.jsonl") if e.event == "artifact.written"]
    assert all(a.get("kind") != "input" for a in artifacts)


def test_a_failed_job_records_its_exit_code(tmp_path: Path) -> None:
    result, experiment = _run(tmp_path, 3, staged_input=False)
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


def test_a_time_limit_ends_the_job_through_its_trap_while_the_simulator_ignores_sigterm(tmp_path: Path) -> None:
    """Regression: at a time limit SLURM sends SIGTERM to every process of the job, then SIGKILL after KillWait. Bash
    runs its TERM trap only once its foreground command returns, so a simulator that outlived the SIGTERM held the trap
    until the SIGKILL: runs 12536-12538 (hung on one node) ended with no job.end, and their SLURM log was never a
    dataset. Waiting on the simulator in the background lets the trap run at once."""
    script, env, experiment = _job(tmp_path, 0, staged_input=False)
    env["FAKE_IGNORE_TERM"] = "1"
    job = subprocess.Popen(  # noqa: S603
        ["bash", "-c", script],  # noqa: S607
        env=env,
        start_new_session=True,  # its own process group, signalled as a whole, as SLURM signals a job
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not (experiment / "output" / "out.txt").exists():  # the simulator wrote its output and hangs
            assert time.monotonic() < deadline, "the fake simulator never started"
            time.sleep(0.05)
        os.killpg(job.pid, signal.SIGTERM)
        code = job.wait(timeout=10)  # before the fix: still blocked here, until a SIGKILL
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):  # macOS: EPERM once the group has exited
            os.killpg(job.pid, signal.SIGKILL)  # the simulator, deaf to SIGTERM
        job.wait()
    assert code == 143
    events = _read(experiment / "events" / "job.jsonl")
    assert [e.event for e in events] == [
        "span.start",
        "job.start",
        "artifact.written",
        "artifact.written",
        "job.end",
        "span.end",
    ]
    assert [events[2].payload["uri"], events[3].payload] == [
        "output/out.txt",
        {"uri": "job.out", "kind": "log", "name": "SLURM log"},
    ]
    assert events[4].level == "error" and events[4].payload["exit_code"] == 143
