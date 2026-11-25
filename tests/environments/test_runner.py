"""The runner composed images run documents with: runtime contract 2 (docs/plan-environment-composition.md, step 2).

It is run here as the image runs it, as a script in a subprocess, on this environment's process-bigraph (the dev
group's, the release composed environments install) and, when uv can fetch it, on that release with events written."""

import hashlib
import importlib.metadata
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from compose_api.common.hpc.slurm_service import SlurmService
from compose_api.environments import runner
from compose_api.registry.environments import load_environments
from compose_api.simulation.hpc_utils import get_slurm_sim_experiment_dir, get_slurm_sim_log_file
from compose_api.simulation.job_script import SimulationJob, simulation_job_script
from tests.fixtures.slurm_fixtures_backend import SlurmBackend
from tests.observability.test_job_script_slurm import _ended

RUNNER = Path(runner.__file__)

COUNTER = """\
from pathlib import Path

from process_bigraph import Process


class Counter(Process):
    config_schema = {"rate": "float", "data": "string"}

    def inputs(self):
        return {"count": "float"}

    def outputs(self):
        return {"count": "float"}

    def update(self, state, interval):
        rate = float(Path(self.config["data"]).read_text()) if self.config["data"] else self.config["rate"]
        return {"count": rate * interval}
"""


def _document(data: str = "") -> dict[str, object]:
    return {
        "count": 0.0,
        "counter": {
            "_type": "process", "address": "local:!counter_mod.Counter", "config": {"rate": 2.0, "data": data},
            "interval": 1.0, "inputs": {"count": ["count"]}, "outputs": {"count": ["count"]},
        },
        "emitter": {
            "_type": "step", "address": "local:RAMEmitter",
            "config": {"emit": {"count": "float", "global_time": "float"}},
            "inputs": {"count": ["count"], "global_time": ["global_time"]},
        },
    }  # fmt: skip


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "counter_mod.py").write_text(COUNTER)
    return tmp_path


def _run(python: list[str], workdir: Path, *args: str, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(  # noqa: S603 the runner, as an image runs it
        [*python, str(RUNNER), *args], cwd=workdir, capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONPATH": str(workdir), **(env or {})},
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]


def _counts(output: Path) -> list[float]:
    (results,) = output.glob("results_*.pber")
    return [row["count"] for row in json.loads(results.read_text())["emitter"]]


def test_a_document_runs_for_the_interval_and_its_results_and_state_are_written(workdir: Path) -> None:
    (workdir / "doc.pbg").write_text(json.dumps({"state": _document()}))
    _run([sys.executable], workdir, "run", "doc.pbg", "-o", "out", "-n", "3")
    assert _counts(workdir / "out") == [0.0, 2.0, 4.0, 6.0]
    assert len(list((workdir / "out").glob("state_*.pbg"))) == 1  # the final state, as pbest saved it


def test_an_archive_runs_with_its_files_found_and_without_the_subcommand(workdir: Path) -> None:
    """pbest's command line had no subcommand, and a document names the archive's files by name alone: they are made
    absolute where the archive is unpacked. A document without `state` is taken to be the state."""
    with zipfile.ZipFile(workdir / "experiment.omex", "w") as archive:
        archive.writestr("experiment.pbg", json.dumps(_document(data="rate.txt")))
        archive.writestr("rate.txt", "5")
    _run([sys.executable], workdir, "experiment.omex", "-o", "out", "-n", "2")
    assert _counts(workdir / "out") == [0.0, 5.0, 10.0]
    assert (workdir / "out" / "rate.txt").read_text() == "5"  # the working directory is kept, as pbest kept it


def test_a_document_is_found_by_name_without_partial_replacements(tmp_path: Path) -> None:
    with zipfile.ZipFile(tmp_path / "a.omex", "w") as archive:
        archive.writestr("a.pbg", json.dumps({"state": {"x": "model.xml", "y": "big-model.xml"}}))
        archive.writestr("model.xml", "")
        archive.writestr("big-model.xml", "")
    unpacked = tmp_path / "unpacked"
    unpacked.mkdir()
    state = runner.load_document(tmp_path / "a.omex", unpacked)["state"]
    assert state == {"x": str(unpacked / "model.xml"), "y": str(unpacked / "big-model.xml")}
    with pytest.raises(ValueError, match=r"expected an \.omex or a \.pbg"):
        runner.load_document(tmp_path / "a.sedml", unpacked)


def test_type_tables_are_registered_from_the_environment(tmp_path: Path) -> None:
    """In a subprocess: building a core discovers every installed package, which in a composed image includes
    pbsim-common's COPASI, which sets the process's locale to C (and would set this process's reads to ASCII)."""
    (tmp_path / "runner_types.py").write_text('standard_types = {"pair_of_floats": {"a": "float", "b": "float"}}\n')
    check = "import runner; assert 'pair_of_floats' in runner.build_core().registry"
    result = subprocess.run(  # noqa: S603 the runner's own function, in a process of its own
        [sys.executable, "-c", check], cwd=tmp_path, capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONPATH": f"{tmp_path}:{RUNNER.parent}", runner.TYPES_ENV: "runner_types"},
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]


TABLE = """\
import pandas as pd
from process_bigraph import Process


class Table(Process):
    def outputs(self):
        return {"table": "node"}

    def update(self, state, interval):
        return {"table": pd.DataFrame({"x": [1.0, 2.0], "n": [3, 4]}, index=[7, 9])}
"""


def test_a_dataframe_in_the_results_is_written_as_its_columns(workdir: Path) -> None:
    """vivarium-tyssue's tissue state is pandas DataFrames: written as ``{column: [values]}``, the shape its solver
    starts from, where `json.dumps` failed the run after it had finished."""
    pytest.importorskip("pandas")
    (workdir / "table_mod.py").write_text(TABLE)
    document = {
        "table_process": {
            "_type": "process", "address": "local:!table_mod.Table", "config": {}, "interval": 1.0,
            "inputs": {}, "outputs": {"table": ["table"]},
        },
        "emitter": {
            "_type": "step", "address": "local:RAMEmitter", "config": {"emit": {"table": "node"}},
            "inputs": {"table": ["table"]},
        },
    }  # fmt: skip
    (workdir / "doc.pbg").write_text(json.dumps({"state": document}))
    _run([sys.executable], workdir, "run", "doc.pbg", "-o", "out", "-n", "2")
    (results,) = (workdir / "out").glob("results_*.pber")
    assert json.loads(results.read_text())["emitter"][-1]["table"] == {"x": [1.0, 2.0], "n": [3, 4]}


def _core() -> dict[str, str]:
    composition = load_environments().composition
    assert composition is not None
    return composition.core


def test_the_runners_tests_run_on_the_engine_composed_images_install() -> None:
    """pyproject's dev pins of the engine are the composed core (environments.yaml), so the tests here exercise the
    runner on what every composed image runs it on."""
    assert {name: importlib.metadata.version(name) for name in _core()} == _core()


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to fetch the composed environments' engine")
def test_on_a_current_engine_the_run_is_a_span_and_its_results_an_artifact(workdir: Path) -> None:
    (workdir / "doc.pbg").write_text(json.dumps({"state": _document()}))
    events = workdir / "engine.jsonl"
    uv = [
        shutil.which("uv") or "uv", "run", "-q", "--isolated", "--no-project", "--python", "3.12",
        *[arg for name, version in sorted(_core().items()) for arg in ("--with", f"{name}=={version}")], "python",
    ]  # fmt: skip
    _run(uv, workdir, "run", "doc.pbg", "-o", "out", "-n", "3", env={"PBG_EVENT_SINKS": f"file:{events}"})
    assert _counts(workdir / "out") == [0.0, 2.0, 4.0, 6.0]
    written = [json.loads(line) for line in events.read_text().splitlines()]
    (artifact,) = [e for e in written if e["event"] == "artifact.written"]
    assert artifact["payload"]["kind"] == "results" and artifact["payload"]["sha256"]
    assert artifact["payload"]["name"].startswith("results_")
    assert any(e["event"] == "span.start" and e["payload"]["name"] == "task" for e in written)


# Checkpoints (COMPOSE_CHECKPOINT_SECONDS): what a stopped run keeps.

SLOW = """\
import time
from pathlib import Path

from process_bigraph import Process


class Slow(Process):
    '''Adds 1 to each of `width` values a step, pausing inside the update; writes the number of updates to `steps`.'''

    config_schema = {"pause": "float", "steps": "string", "fork_at": "integer"}

    def initialize(self, config):
        self.count = 0

    def inputs(self):
        return {"values": "map[float]"}

    def outputs(self):
        return {"values": "map[float]"}

    def update(self, state, interval):
        time.sleep(self.config["pause"])
        self.count += 1
        if self.count == self.config["fork_at"]:  # a worker process, stopped as multiprocessing stops one: SIGTERM
            import multiprocessing

            worker = multiprocessing.get_context("fork").Process(target=time.sleep, args=(60,))
            worker.start()
            time.sleep(0.2)
            worker.terminate()
            worker.join()
            Path(self.config["steps"]).with_name("forked").write_text(str(worker.exitcode))
        if self.config["steps"]:
            Path(self.config["steps"]).write_text(str(self.count))
        return {"values": {key: 1.0 for key in state["values"]}}
"""


def _slow_state(steps: str, width: int, pause: float, fork_at: int = 0) -> dict[str, Any]:
    return {
        "values": {f"x{i}": 0.0 for i in range(width)},
        "slow": {
            "_type": "process", "address": "local:!slow_mod.Slow",
            "config": {"pause": pause, "steps": steps, "fork_at": fork_at},
            "interval": 1.0, "inputs": {"values": ["values"]}, "outputs": {"values": ["values"]},
        },
        "emitter": {
            "_type": "step", "address": "local:RAMEmitter",
            "config": {"emit": {"values": "map[float]", "global_time": "float"}},
            "inputs": {"values": ["values"], "global_time": ["global_time"]},
        },
    }  # fmt: skip


def _slow_document(workdir: Path, width: int, pause: float, fork_at: int = 0) -> Path:
    (workdir / "slow_mod.py").write_text(SLOW)
    path = workdir / "slow.pbg"
    path.write_text(json.dumps({"state": _slow_state(str(workdir / "steps"), width, pause, fork_at)}))
    return path


def _start(workdir: Path, interval: int, checkpoint: str | None) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": str(workdir)}
    env.pop(runner.CHECKPOINT_ENV, None)
    if checkpoint is not None:
        env[runner.CHECKPOINT_ENV] = checkpoint
    return subprocess.Popen(  # noqa: S603 the runner, as an image runs it
        [sys.executable, str(RUNNER), "run", "slow.pbg", "-o", "out", "-n", str(interval)],
        cwd=workdir, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )  # fmt: skip


def _until(condition: Callable[[], bool], what: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.01)


def _steps(workdir: Path) -> int:
    text = (workdir / "steps").read_text() if (workdir / "steps").exists() else ""
    return int(text) if text else 0


def _rows(output: Path) -> list[dict[str, Any]]:
    (results,) = output.glob("results_*.pber")
    rows: list[dict[str, Any]] = json.loads(results.read_text())["emitter"]
    return rows


def _assert_whole(rows: list[dict[str, Any]], width: int) -> None:
    """Row k is the state after k steps: every value k, at time k."""
    for k, row in enumerate(rows):
        assert row["global_time"] == k
        assert row["values"] == {f"x{i}": float(k) for i in range(width)}, f"row {k} is not whole"


def test_a_stopped_run_keeps_its_rows_so_far_when_checkpoints_are_on(workdir: Path) -> None:
    """SIGTERM (a time limit, scancel) writes the rows so far and exits 143; the hour between writes never passes."""
    _slow_document(workdir, width=3, pause=0.05)
    process = _start(workdir, interval=1000, checkpoint="3600")
    _until(lambda: _steps(workdir) >= 5, "five steps")
    process.terminate()
    assert process.wait(timeout=60) == 143, process.stderr.read() if process.stderr else ""
    rows = _rows(workdir / "out")
    assert len(rows) >= 5
    _assert_whole(rows, width=3)
    assert not list((workdir / "out").glob(".*.part"))  # the write finished before the exit


def test_a_second_sigterm_during_the_write_lets_it_finish(workdir: Path) -> None:
    """scancel and then the time limit, or a signal sent twice: the second SIGTERM lands while the first one's write of
    100 rows of 20,000 values is under way. The write finishes, whole, and the runner exits 143; a handler run again
    would wait forever on the lock its own write holds."""
    width = 20000
    _slow_document(workdir, width=width, pause=0.0)
    process = _start(workdir, interval=100000, checkpoint="3600")
    try:
        _until(lambda: _steps(workdir) >= 100, "100 steps")
        process.terminate()
        time.sleep(0.05)
        process.terminate()
        assert process.wait(timeout=30) == 143
    finally:
        process.kill()
    rows = _rows(workdir / "out")
    assert len(rows) >= 100
    _assert_whole(rows, width=width)


def test_a_forked_worker_stopped_with_sigterm_writes_nothing(workdir: Path) -> None:
    """A worker forked from the run inherits its signal handlers, and multiprocessing stops one with SIGTERM (as
    leaving a Pool does): the worker ends as it would have without checkpoints, killed by the signal, and only the
    run's own handler writes the file, never a worker from its stale copy of the rows."""
    _slow_document(workdir, width=3, pause=0.05, fork_at=5)
    process = _start(workdir, interval=1000, checkpoint="3600")
    try:
        _until(lambda: (workdir / "forked").exists() and (workdir / "forked").read_text() != "", "the worker's end")
        assert (workdir / "forked").read_text() == str(-signal.SIGTERM)
        assert not list((workdir / "out").glob("results_*.pber")), "a worker wrote the run's results"
        process.terminate()
        assert process.wait(timeout=60) == 143
    finally:
        process.kill()
    rows = _rows(workdir / "out")
    assert len(rows) >= 5
    _assert_whole(rows, width=3)


def test_a_run_killed_outright_keeps_the_last_periodic_write(workdir: Path) -> None:
    """SIGKILL, as an out-of-memory kill or SLURM after KillWait, runs no handler: the last periodic write is kept."""
    _slow_document(workdir, width=3, pause=0.05)
    process = _start(workdir, interval=1000, checkpoint="0.2")
    output = workdir / "out"
    _until(lambda: any(output.glob("results_*.pber")) and len(_rows(output)) >= 3, "a write of three rows")
    process.kill()
    process.wait(timeout=60)
    _assert_whole(_rows(output), width=3)


@pytest.mark.parametrize("checkpoint", [None, "0"])  # unset, and the 0 compose-api's job sends when off
def test_without_checkpoints_a_stopped_run_keeps_nothing_as_before(workdir: Path, checkpoint: str | None) -> None:
    """Off: no thread and no handler, so SIGTERM ends the runner as it always did, before anything is written."""
    _slow_document(workdir, width=3, pause=0.05)
    process = _start(workdir, interval=1000, checkpoint=checkpoint)
    _until(lambda: _steps(workdir) >= 5, "five steps")
    process.terminate()
    assert process.wait(timeout=60) == -signal.SIGTERM
    assert not list((workdir / "out").iterdir())


def _finished(workdir: Path, checkpoint: str | None) -> bytes:
    """The results file of a 40-step run, which must see a write while it runs when checkpoints are on."""
    workdir.mkdir()
    _slow_document(workdir, width=3, pause=0.02)
    process, output = _start(workdir, interval=40, checkpoint=checkpoint), workdir / "out"
    if checkpoint is not None:
        _until(lambda: any(output.glob("results_*.pber")) and process.poll() is None, "a write while the run runs")
    assert process.wait(timeout=120) == 0, process.stderr.read() if process.stderr else ""
    assert not list(output.glob(".*.part"))
    (results,) = output.glob("results_*.pber")
    return results.read_bytes()


def test_a_finished_runs_results_are_the_same_with_checkpoints_on(tmp_path: Path) -> None:
    """The finished run replaces the rows written while it ran with its whole results, byte for byte what it writes
    without checkpoints, in one results file."""
    without = _finished(tmp_path / "without", checkpoint=None)
    assert _finished(tmp_path / "with", checkpoint="0.05") == without
    assert len(json.loads(without)["emitter"]) == 41


def test_every_row_written_while_a_process_is_mid_update_is_whole(workdir: Path) -> None:
    """Writes every 10 ms while the process's update makes 20,000 values and while they are applied one by one: every
    write read here holds only whole rows, because a row is the emitter's copy of the state, made after the step's
    updates are applied. A write that read the state itself fails here (at 20,000; at 5,000 the apply is too quick to
    catch)."""
    width = 20000
    _slow_document(workdir, width=width, pause=0.0)
    process = _start(workdir, interval=40, checkpoint="0.01")
    output, seen = workdir / "out", set()
    while process.poll() is None:
        if any(output.glob("results_*.pber")):
            rows = _rows(output)
            _assert_whole(rows, width=width)
            seen.add(len(rows))
    assert process.returncode == 0, process.stderr.read() if process.stderr else ""
    assert len(seen) >= 10  # read while the run grew
    _assert_whole(_rows(output), width=width)


# The runner in an image on the composed core, run the way every composed image runs it: bash execs python, so under
# --compat (its own PID namespace, no init) the runner is the container's PID 1.
IMAGE = """\
Bootstrap: docker
From: python:3.12-slim

%files
    {files}/runner.py /opt/compose-api/runner.py
    {files}/slow_mod.py /opt/compose-api/slow_mod.py

%post
    pip install --no-cache-dir {pins}

%environment
    export PYTHONPATH=/opt/compose-api

%runscript
exec /bin/bash -c 'exec python /opt/compose-api/runner.py "$@"' runner "$@"
"""


@pytest.mark.slurm
@pytest.mark.asyncio
async def test_a_run_stopped_at_its_slurm_time_limit_keeps_its_rows_so_far(
    slurm_backend: SlurmBackend, slurm_service: SlurmService
) -> None:
    """The real job script and the runner in a --compat container, at a one-minute time limit, with writes an hour
    apart: only SIGTERM can write the rows, so they show that it reaches the container's PID 1 and its handler, and,
    whole, that the write finished before SLURM's SIGKILL, KillWait later. The job announces them like any output
    file. The job runs as the backend's user (root on the test cluster)."""
    if not slurm_backend.can_build_singularity:
        pytest.skip(f"the {slurm_backend.kind} backend cannot build singularity images")
    ssh = slurm_backend.ssh_service
    experiment_id = f"checkpoint-{uuid.uuid4().hex[:8]}"
    experiment = get_slurm_sim_experiment_dir(experiment_id)
    files, image = experiment / "image", experiment / "image" / "runner.sif"
    pins = " ".join(f"{name}=={version}" for name, version in sorted(_core().items()))
    script = simulation_job_script(
        SimulationJob(
            job_name=experiment_id, experiment_id=experiment_id, simulation_id=1,
            correlation_id=f"simulation-{experiment_id}", experiment_dir=str(experiment), container=str(image),
            file_suffix="pbg", output_dir="/experiment/output", end_time=10000.0,
            log_file=str(get_slurm_sim_log_file(experiment_id)), is_batch=True,
            partition=slurm_backend.partition, qos=slurm_backend.qos, time_limit_minutes=1, checkpoint_seconds=3600,
        )
    )  # fmt: skip
    await ssh.run_command(f"mkdir -p {shlex.quote(str(files))}")
    job_id = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp)
            uploads = {
                files / "runner.py": RUNNER.read_text(),
                files / "slow_mod.py": SLOW,
                files / "runner.def": IMAGE.format(files=files, pins=pins),
                experiment / f"{experiment_id}.pbg": json.dumps({"state": _slow_state("", width=3, pause=0.5)}),
                experiment / "job.sbatch": script,
            }
            for remote, text in uploads.items():
                (local / remote.name).write_text(text)
                await ssh.scp_upload(local_file=local / remote.name, remote_path=remote)
        code, out, err = await ssh.run_command(
            f"cd {shlex.quote(str(files))} && singularity build --fakeroot runner.sif runner.def"
        )
        assert code == 0, (out + err)[-3000:]
        code, out, err = await ssh.run_command(
            f"cd {shlex.quote(str(experiment))} && sbatch --parsable --mem=500M --cpus-per-task=1 job.sbatch"
        )
        assert code == 0, err
        job_id = int(out.strip().split(";")[0])
        assert (await _ended(slurm_service, job_id)).startswith("TIMEOUT")

        output = shlex.quote(str(experiment / "output"))
        _, names, _ = await ssh.run_command(f"ls -A {output}")
        (name,) = [n for n in names.split() if n.startswith("results_")]
        assert not [n for n in names.split() if n.endswith(".part")]
        _, text, _ = await ssh.run_command(f"cat {output}/{shlex.quote(name)}")
        rows = json.loads(text)["emitter"]
        assert len(rows) >= 10, len(rows)  # about two a second for most of a minute
        _assert_whole(rows, width=3)
        assert rows[-1]["global_time"] < 10000

        _, log, _ = await ssh.run_command(f"cat {shlex.quote(str(experiment / 'events' / 'job.jsonl'))}")
        events = [json.loads(line) for line in log.splitlines() if line.strip()]
        (end,) = [e for e in events if e["event"] == "job.end"]
        assert end["payload"]["exit_code"] == 143
        written = [e for e in events if e["event"] == "artifact.written"]
        *_, announced = [e for e in written if e["payload"]["uri"] == f"output/{name}"]  # both manifests may see it
        assert announced["payload"]["sha256"] == hashlib.sha256(text.encode()).hexdigest()
        _, left, _ = await ssh.run_command(f"ls -A {shlex.quote(str(experiment))}")
        assert "results.zip" not in left.split()  # results.zip still means a finished run
    finally:
        if job_id is not None:
            await ssh.run_command(f"scancel {job_id}")
        await ssh.run_command(f"rm -rf {shlex.quote(str(experiment))}")
