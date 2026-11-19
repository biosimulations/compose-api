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
from collections.abc import Callable
from pathlib import Path

import pytest

from compose_api.observability.datasets import DatasetRow, artifact_records, merge
from compose_api.observability.events import RunSpan, apply_span_events, parse_complete_lines
from compose_api.observability.identity import job_span_id, trace_id_from_correlation
from compose_api.simulation.job_script import SimulationJob, simulation_job_script

CORRELATION = "simulation-abc1234"

# Stands in for `singularity run --compat --env-file F --bind HOST:/experiment IMAGE run ...`: reads the env file the
# way apptainer does, writes one engine event under the run's traceparent and one output file, then exits FAKE_EXIT.
FAKE_SINGULARITY = r"""#!/bin/bash
if [ -n "${FAKE_IGNORE_TERM:-}" ]; then trap '' TERM; fi  # first, so no SIGTERM can land before it
if [ -n "${FAKE_FLUSH_ON_TERM:-}" ]; then  # a simulator with a shutdown handler: its final output comes after SIGTERM
  trap 'sleep 1; echo flushed > "$HOST/output/out.txt"; exit 0' TERM
fi
while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) set -a; . "$2"; set +a; shift 2 ;;
    --bind) HOST="${2%%:*}"; shift 2 ;;
    *) shift ;;
  esac
done
if [ -n "${FAKE_PIDFILE:-}" ]; then echo $$ > "$HOST/sim.pid"; fi
TRACE=$(echo "$PBG_TRACEPARENT" | cut -d- -f2); PARENT=$(echo "$PBG_TRACEPARENT" | cut -d- -f3)
SINK="${PBG_EVENT_SINKS#file:}"; SINK="$HOST${SINK#/experiment}"
printf '{"v":1,"ts":"2026-10-07T12:00:01.000Z","seq":1,"source":"node-42","component":"process_bigraph","event":"run.start","level":"info","trace_id":"%s","span_id":null,"parent_span_id":"%s","baggage":{"simulation_id":"%s"},"payload":{}}\n' "$TRACE" "$PARENT" "$PBG_TRACE_BAGGAGE" >> "$SINK"
echo result > "$HOST/output/out.txt"
if [ -n "${FAKE_BUNDLE:-}" ]; then  # a zarr store: a directory of chunk files, announced as one dataset
  mkdir -p "$HOST/output/run.fenics/u"; echo '{}' > "$HOST/output/run.fenics/.zattrs"; printf 'abcd' > "$HOST/output/run.fenics/u/0.0"
  chmod 600 "$HOST/output/run.fenics/.zattrs"  # as a mkstemp file renamed into place
fi
if [ -n "${FAKE_IGNORE_TERM:-}${FAKE_FLUSH_ON_TERM:-}${FAKE_PIDFILE:-}" ]; then  # still running when the job is stopped
  while :; do sleep 1; done
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


def _stopped(tmp_path: Path, fake_mode: str) -> tuple[subprocess.Popen[bytes], Path]:
    """The job with the fake simulator in ``fake_mode``, stopped as SLURM stops a job at its time limit: SIGTERM to
    every process of the job once the simulator has written its output."""
    script, env, experiment = _job(tmp_path, 0, staged_input=False)
    env[fake_mode] = "1"
    job = subprocess.Popen(  # noqa: S603
        ["bash", "-c", script],  # noqa: S607
        env=env,
        start_new_session=True,  # its own process group, signalled as a whole, as SLURM signals a job
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60  # generous: it only matters when the fake never starts
        while not (experiment / "output" / "out.txt").exists():
            assert time.monotonic() < deadline, "the fake simulator never started"
            time.sleep(0.05)
        os.killpg(job.pid, signal.SIGTERM)
    except BaseException:
        _kill(job)
        raise
    return job, experiment


def _kill(job: subprocess.Popen[bytes]) -> None:
    """SLURM's SIGKILL at KillWait, to everything left in the job."""
    with contextlib.suppress(ProcessLookupError, PermissionError):  # macOS: EPERM once the group has exited
        os.killpg(job.pid, signal.SIGKILL)
    job.wait()


def _until(predicate: Callable[[], bool], what: str, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds  # generous: it only matters when something is wrong
    while not predicate():
        assert time.monotonic() < deadline, what
        time.sleep(0.05)


def test_a_time_limit_records_the_job_end_while_the_simulator_ignores_sigterm(tmp_path: Path) -> None:
    """Regression: bash runs its TERM trap only once its foreground command returns, so a simulator that outlived
    SLURM's SIGTERM (runs 12536-12538, hung on one node) held the trap until the SIGKILL: no job.end, and the SLURM log
    never became a dataset. Now the end is recorded at once, and the script then stays in the job, so the simulator is
    not orphaned outside SLURM's process tracking: SLURM's SIGKILL ends both."""
    job, experiment = _stopped(tmp_path, "FAKE_IGNORE_TERM")
    events_file = experiment / "events" / "job.jsonl"
    try:
        _until(lambda: "span.end" in events_file.read_text(), "the end was not recorded after SIGTERM")
        time.sleep(0.5)
        assert job.poll() is None  # still in the job with the simulator
    finally:
        _kill(job)
    events = _read(events_file)
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


def test_files_a_simulator_finishes_writing_after_sigterm_are_what_the_datasets_describe(tmp_path: Path) -> None:
    """A simulator with a shutdown handler writes its final output after SIGTERM. The end is recorded at once, with the
    file as it was; when the simulator then exits, its files are announced again, and compose-api's own dataset
    registration (artifact_records, then merge, in event order) keeps the final file's checksum. The job then exits on
    its own."""
    job, experiment = _stopped(tmp_path, "FAKE_FLUSH_ON_TERM")
    try:
        code = job.wait(timeout=60)
    finally:
        _kill(job)
    assert code == 143
    out = experiment / "output" / "out.txt"
    assert out.read_text() == "flushed\n"
    events = _read(experiment / "events" / "job.jsonl")
    assert [e.event for e in events][-4:] == ["job.end", "span.end", "artifact.written", "artifact.written"]
    rows: dict[str, DatasetRow] = {}
    for record in artifact_records(events):
        rows[record.path] = merge(rows.get(record.path), record)
    assert rows["output/out.txt"].sha256 == hashlib.sha256(out.read_bytes()).hexdigest()


@pytest.mark.parametrize("skew", [0.001, 0.003, 0.005, 0.01])
def test_a_second_sigterm_while_the_end_is_recorded_does_not_cut_it_short(tmp_path: Path, skew: float) -> None:
    """SLURM signals every process of the job, the simulator first by a few milliseconds at most. A simulator without a
    handler dies at once; the script then records the end, and its own SIGTERM arrives in the middle of that. It must
    not cut the record short."""
    script, env, experiment = _job(tmp_path, 0, staged_input=False)
    env["FAKE_PIDFILE"] = "1"
    job = subprocess.Popen(  # noqa: S603
        ["bash", "-c", script],  # noqa: S607
        env=env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid_file = experiment / "sim.pid"
    try:
        _until(lambda: (experiment / "output" / "out.txt").exists() and pid_file.read_text().strip() != "", "no start")
        os.kill(int(pid_file.read_text()), signal.SIGTERM)
        time.sleep(skew)
        os.kill(job.pid, signal.SIGTERM)
        code = job.wait(timeout=60)
    finally:
        _kill(job)
    assert code == 143
    events = [e.event for e in _read(experiment / "events" / "job.jsonl")]
    assert events[-2:] == ["job.end", "span.end"], events
