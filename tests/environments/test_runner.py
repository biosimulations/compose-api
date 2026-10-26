"""The runner composed images run documents with: runtime contract 2 (docs/plan-environment-composition.md, step 2).

It is run here as the image runs it, as a script in a subprocess, on this environment's process-bigraph (pbest's 1.0.5,
no events) and, when uv can fetch it, on the release composed environments target (1.9.1, with events)."""

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from compose_api.environments import runner

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
    """In a subprocess: building a core discovers every installed package, pbsim-common's COPASI included, which sets
    the process's locale to C (and this test process's reads to ASCII)."""
    (tmp_path / "runner_types.py").write_text('standard_types = {"pair_of_floats": {"a": "float", "b": "float"}}\n')
    check = "import runner; assert 'pair_of_floats' in runner.build_core().registry"
    result = subprocess.run(  # noqa: S603 the runner's own function, in a process of its own
        [sys.executable, "-c", check], cwd=tmp_path, capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONPATH": f"{tmp_path}:{RUNNER.parent}", runner.TYPES_ENV: "runner_types"},
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to fetch the composed environments' engine")
def test_on_a_current_engine_the_run_is_a_span_and_its_results_an_artifact(workdir: Path) -> None:
    (workdir / "doc.pbg").write_text(json.dumps({"state": _document()}))
    events = workdir / "engine.jsonl"
    uv = [
        shutil.which("uv") or "uv", "run", "-q", "--isolated", "--no-project", "--python", "3.12",
        "--with", "process-bigraph==1.9.1", "--with", "bigraph-schema==1.8.1", "python",
    ]  # fmt: skip
    _run(uv, workdir, "run", "doc.pbg", "-o", "out", "-n", "3", env={"PBG_EVENT_SINKS": f"file:{events}"})
    assert _counts(workdir / "out") == [0.0, 2.0, 4.0, 6.0]
    written = [json.loads(line) for line in events.read_text().splitlines()]
    (artifact,) = [e for e in written if e["event"] == "artifact.written"]
    assert artifact["payload"]["kind"] == "results" and artifact["payload"]["sha256"]
    assert artifact["payload"]["name"].startswith("results_")
    assert any(e["event"] == "span.start" and e["payload"]["name"] == "task" for e in written)
