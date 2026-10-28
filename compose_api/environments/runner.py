"""The entry point of a composed environment's image: runtime contract 2 (docs/plan-environment-composition.md, step 2).

compose-api's job runs ``singularity run --compat <image> run /experiment/<id>.<suffix> -o /experiment/output -n
<interval>``, the command line prebuilt images already answer (``simulation/job_script.py``), and zips the output
directory. This module answers it in place of pbest's ``main.py``, which pinned process-bigraph 1.0.5. It is written
into every composed image as one file, so it imports the standard library and the environment's process-bigraph only,
never compose-api.

What a run does, as pbest's did (``pbest/execution/local.py``), so results and SED-ML reports land where compose-api
reads them:

- the archive is unpacked into a working directory, and every file name the document mentions is made absolute there;
- the first ``.pbg`` is run as a ``Composite`` (a document without ``state`` is taken to be the state) for the
  interval, on a core with the types the environment declares (``COMPOSE_RUNNER_TYPES``, below);
- ``results_<date>[<tz>#<time>].pber`` is ``gather_emitter_results`` as JSON, the final state is saved as
  ``state_<date>#<time>.pbg``, and the working directory (what the run wrote there) is copied into the output.

And, after viva-pde-particle's runner, on an engine that has process-bigraph's events (>= 1.8.5): the run is one
``task`` span, and the results file is announced as an ``artifact.written`` event of kind ``results``.

``COMPOSE_RUNNER_TYPES`` names the type tables to register, ``module:attribute`` separated by commas (for example
``pbsim_common:standard_types``); the image sets it from its entries.

    python runner.py run experiment.omex -o output -n 10
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import importlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

TYPES_ENV = "COMPOSE_RUNNER_TYPES"
COMPONENT = "compose_api.runner"


class _Emitter(Protocol):
    """What the runner uses of process-bigraph's event emitter (``process_bigraph.events``, >= 1.8.5)."""

    def span(self, name: str, **attributes: object) -> contextlib.AbstractContextManager[object]: ...

    def event(self, event: str, /, **fields: object) -> None: ...

    def flush(self) -> None: ...


def _jsonable(value: object) -> object:
    """Numbers and arrays as JSON (NumPy is not imported unless the results hold its types)."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):  # numpy arrays and scalars
        return tolist()
    return value


def load_document(path: Path, workdir: Path) -> dict[str, Any]:
    """The document to run: the first ``.pbg`` in an archive (unpacked into ``workdir``, with the archive's file names
    made absolute in it, as pbest did), or the ``.pbg`` given."""
    if path.suffix == ".omex":
        with zipfile.ZipFile(path) as archive:
            archive.extractall(workdir)
        documents = sorted(workdir.glob("*.pbg")) or sorted(workdir.rglob("*.pbg"))
        if not documents:
            raise FileNotFoundError(f"no .pbg in {path}")
        names = sorted((p.name for p in workdir.iterdir() if p.suffix != ".pbg"), key=len, reverse=True)
        text = documents[0].read_text()
        if names:  # one pass, whole names only: `model.xml` is not replaced inside `big-model.xml` (pbest did that)
            pattern = re.compile(r"(?<![\w./-])(" + "|".join(map(re.escape, names)) + r")(?![\w.-])")
            text = pattern.sub(lambda m: str(workdir / m.group(1)), text)
        document: dict[str, Any] = json.loads(text)
    elif path.suffix in (".pbg", ".json"):
        document = json.loads(path.read_text())
    else:
        raise ValueError(f"expected an .omex or a .pbg, not {path.name}")
    return document if "state" in document else {"state": document}


def build_core() -> object:
    """process-bigraph's core, with the type tables ``COMPOSE_RUNNER_TYPES`` names registered."""
    from process_bigraph import allocate_core

    core = allocate_core()
    for name in filter(None, (n.strip() for n in os.environ.get(TYPES_ENV, "").split(","))):
        module, _, attribute = name.partition(":")
        table = getattr(importlib.import_module(module), attribute or "standard_types")
        for type_name, schema in table.items():
            core.register_type(type_name, schema)
    return core


def _emitter() -> _Emitter | None:
    """process-bigraph's event emitter (configured from the job's ``PBG_*`` variables), or None on an engine without
    events."""
    try:
        from process_bigraph import events
    except ImportError:
        return None
    emitter: _Emitter = events.get_emitter()
    return emitter


@contextlib.contextmanager
def _span(emitter: _Emitter | None, name: str, **attributes: object) -> Iterator[None]:
    if emitter is None:
        yield
        return
    with emitter.span(name, **attributes):
        yield


def _announce(emitter: _Emitter | None, results: Path) -> None:
    """``artifact.written`` for the results file: compose-api records it as a dataset of kind ``results``."""
    if emitter is None:
        return
    data = results.read_bytes()
    emitter.event(
        "artifact.written", component=COMPONENT, uri=str(results.resolve()), kind="results", name=results.name,
        bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), attributes={"format": "pber"},
    )  # fmt: skip


def _stamp() -> tuple[str, str]:
    """pbest's file-name stamps: ``<date>[<tz>#<time>]`` for results, ``<date>#<time>`` for the state."""
    now = datetime.datetime.now()
    date, time = str(now.date()), str(now.time()).replace(":", "-")
    return f"{date}[{now.tzinfo}#{time}]", f"{date}#{time}"


def run(path: Path, output: Path, interval: float) -> Path | None:
    """Run the document for ``interval`` and write its results into ``output``; the results file (None when the
    document emits nothing)."""
    from process_bigraph import Composite, gather_emitter_results

    emitter = _emitter()
    output.mkdir(parents=True, exist_ok=True)
    results_file: Path | None = None
    with _span(emitter, "task", document=path.name, interval=interval), tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        document = load_document(path, workdir)
        composite = Composite(document, core=build_core())
        composite.run(interval)
        results = gather_emitter_results(composite)
        results_stamp, state_stamp = _stamp()
        if results:
            results_file = output / f"results_{results_stamp}.pber"
            keyed = {"/".join(map(str, k)) if isinstance(k, tuple) else str(k): v for k, v in results.items()}
            results_file.write_text(json.dumps(_jsonable(keyed)))
        with contextlib.suppress(Exception):  # the state is a convenience: a run never fails for want of it
            composite.save(filename=f"state_{state_stamp}.pbg", outdir=str(workdir))
        shutil.copytree(workdir, output, dirs_exist_ok=True)
        if results_file is not None:
            _announce(emitter, results_file)
    if emitter is not None:
        emitter.flush()
    return results_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="runner", description="Run a process-bigraph document for compose-api.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run a document (.omex or .pbg)")
    run_parser.add_argument("input", type=Path)
    run_parser.add_argument("-o", "--output", type=Path, default=Path("output"))
    run_parser.add_argument("-n", "--interval", type=float, default=1.0)
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] not in ("run", "-h", "--help"):
        args = ["run", *args]  # `<doc> -o <dir> -n <t>` without the subcommand, as pbest's runscript took it
    parsed = parser.parse_args(args)
    results = run(parsed.input, parsed.output, parsed.interval)
    print(f"results written to {results}" if results else "the document emitted no results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
