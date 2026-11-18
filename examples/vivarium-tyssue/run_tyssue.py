# /// script
# requires-python = ">=3.11"
# dependencies = ["compose-api-client==0.7.72", "matplotlib==3.11.2", "pyyaml==6.0.3"]
# [tool.uv]
# exclude-newer = "2026-11-18T00:00:00Z"
# ///
"""Run vivarium-tyssue on compose-api and check what comes back.

    uv run examples/vivarium-tyssue/run_tyssue.py [--base-url URL] [--out DIR]

It needs nothing but the network:

1. **Introspect** the service:
   - the registry entry `vivarium-tyssue` (its level, pinned commit and module roots);
   - the environment that provides it, and that its default version installs the entry's pinned commit;
   - that version's compliance report: each entry's level, and the classes a generic check refuses;
   - the classes the environment's interface manifest lists for the entry.
2. **Run the entry's compliance case on the service.** The case is `sheet-relaxation`: tyssue's flat test sheet
   relaxing for 32 explicit Euler steps. The script fetches the case from compose-api's repository at the release tag,
   checked by sha256, and checks every expectation the case states. Those expected values are tyssue's own solver's,
   not this package's.
3. **Show that a mesh which would run code is refused.** pandas unpickles object columns in HDF5. The script submits
   the case with such a file beside it (the release's own test fixture, whose pickle only prints) and checks that
   submission refuses it. A refused submission records nothing.
4. **Run a workspace regulator on the same sheet.** `CellDivisions` triggers divisions as a Poisson process and draws
   from NumPy's unseeded generator, so the cell count changes from run to run. The checks are therefore what must hold
   in any run: the sheet gains cells, every edge joins two of its vertices, every vertex is on an edge, and every
   face has edges.
5. **Draw** the sheet before and after each run into `tyssue-on-compose.png`.

It exits 0 when every check passes and 1 otherwise. Runs are anonymous. Set `COMPOSE_API_TOKEN` to run signed in,
which the very first run of a new environment needs, since that run builds it.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import yaml
from compose_api_client.ext.errors import ApiError, CliError
from compose_api_client.ext.session import ComposeSession

ENTRY = "vivarium-tyssue"
RELEASE = "0.7.89"
SOURCE = f"https://raw.githubusercontent.com/biosimulations/compose-api/{RELEASE}/"
CASE = "compose_api/registry/compliance/vivarium-tyssue/sheet-relaxation/"
CASE_FILES = {
    "case.yaml": "e460c8c5f237ed04e1269cf1dcf7046a66fadcd66fb15becf1381feef9a647c4",
    "document.pbg": "13c3464238a23554e99066256ab8ff2c05eb867257df7c47b1782f74e376ee93",
    "test_square.hf5": "4f0dff6ce37aa3c3c53b9b22176050a01ec5de613d2aa3d8df0bd1c6a4275699",
}
# a pandas file with an object column whose pickle prints a line (tests/fixtures/resources/hdf5/README.md)
UNSAFE_MESH = (
    "tests/fixtures/resources/hdf5/object_column.h5",
    "16bb637ddc5aa66b831ce7d9b24231412fc94581df8bb7297ee60eff2b9c0a8c",
)
LEVELS = ("tested", "validated", "curated")  # the service runs these
REL, ABS = 1e-6, 1e-9  # compose_api.environments.compliance.Expectation's defaults
RUN_TIMEOUT = 3600.0


class Failure(Exception):
    """Something this script cannot go on from; printed as a failed check."""


class Checks:
    def __init__(self) -> None:
        self.failed = 0

    def __call__(self, ok: bool, what: str) -> bool:
        print(f"  [{'ok' if ok else 'FAIL'}] {what}")
        self.failed += not ok
        return ok


def fetch(path: str, digest: str) -> bytes:
    """A file of compose-api's repository at the release tag, checked against its sha256."""
    with urllib.request.urlopen(SOURCE + path, timeout=60) as response:  # noqa: S310 (a fixed https URL)
        data: bytes = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise Failure(f"{path} at {RELEASE} does not match its sha256")
    return data


def introspect(session: ComposeSession, base_url: str, check: Checks) -> str | None:
    """The environment to run in, after checking what the service says about the entry and it; None when there is
    none yet (the first signed-in run makes it)."""
    print(f"service {base_url}, version {session.version()}")
    entry = next((e for e in session.catalog() if e.id == ENTRY), None)
    check(entry is not None, f"the registry lists {ENTRY}")
    if entry is None:
        return None
    print(f"  level {entry.level}, commit {entry.commit}, module roots {list(entry.module_roots or [])}")
    check(str(entry.level) in LEVELS, f"{ENTRY} is at a level the service runs ({entry.level})")

    environment = next((e for e in session.environments() if any(r.id == ENTRY for r in e.entries or [])), None)
    if environment is None:
        print("  no environment provides it yet: the first signed-in run makes one (set COMPOSE_API_TOKEN)")
        return None
    default = session.environment_versions(environment.name).default
    if not isinstance(default, int):
        check(False, f"{environment.name} has a default version")
        return environment.name
    spec = session.environment_version(environment.name, default).spec
    installed = spec.to_dict() if hasattr(spec, "to_dict") else dict(spec or {})
    commits = [e.get("install", {}).get("commit") for e in installed.get("entries", []) if e.get("id") == ENTRY]
    print(f"  environment {environment.name}@{default}, process-bigraph {environment.process_bigraph}")
    check(commits == [entry.commit], f"{environment.name}@{default} installs the pinned commit ({commits})")

    report = session.environment_compliance(environment.name, default)
    deadline = time.monotonic() + 1800  # a version's cases may still be running; runs are refused until they finish
    while {e.entry: str(e.level) for e in report.entries}.get(ENTRY) == "pending" and time.monotonic() < deadline:
        print(f"  its compliance cases are still running in {environment.name}@{default}; waiting")
        time.sleep(30)
        report = session.environment_compliance(environment.name, default)
    levels = {e.entry: str(e.level) for e in report.entries}
    refused = set(report.refused or [])
    print(f"  compliance: {levels}; refused: {sorted(refused)}")
    check(levels.get(ENTRY) == "tested", f"{ENTRY}'s cases passed in {environment.name}@{default}")

    classes = {
        f"{c.module}.{c.name}": c.kind
        for c in session.environment_manifest(environment.name).components
        if getattr(c.registry_entry, "id", None) == ENTRY
    }
    for name, kind in sorted(classes.items()):
        print(f"    {'refused' if name in refused else 'runs   '}  {name} ({kind})")
    solver = "vivarium_tyssue.processes.eulersolver.EulerSolver"
    check(solver in classes and solver not in refused, "EulerSolver is provided and not refused")
    return environment.name


def pack(directory: Path, document: dict[str, Any], name: str, extra: dict[str, bytes] | None = None) -> Path:
    archive = directory / name
    with zipfile.ZipFile(archive, "w") as omex:
        omex.writestr("document.pbg", json.dumps(document))
        omex.write(directory / "test_square.hf5", "test_square.hf5")
        for member, data in (extra or {}).items():
            omex.writestr(member, data)
    return archive


def run(session: ComposeSession, archive: Path, interval: float, environment: str | None, out: Path) -> dict[str, Any]:
    """Submit an archive, wait for it, and return its results (each emitter's rows)."""
    submitted = session.submit(archive, interval=interval, environment=environment, tags=["vivarium-tyssue-demo"])
    simulation = submitted.simulation_database_id
    print(f"  simulation {simulation} submitted; waiting")
    state = session.wait(simulation, poll=10, timeout=RUN_TIMEOUT, on_update=lambda s: print(f"    {s.status}"))
    if not state.ok:
        raise Failure(f"simulation {simulation} ended {state.status}")
    files = session.extract(simulation, out / f"simulation-{simulation}")
    results = [f for f in files if f.name.startswith("results_") and f.suffix == ".pber"]
    if len(results) != 1:
        raise Failure(f"simulation {simulation} returned {len(results)} results files, not one")
    found: dict[str, Any] = json.loads(results[0].read_text())
    return found


def at(row: object, field: str) -> float:
    """The number at a dotted ``field`` path into a results row (lists by index, maps by key)."""
    found: Any = row
    for step in field.split("."):
        found = found[int(step)] if isinstance(found, list) else found[step]
    return float(found)


def check_case(case: dict[str, Any], results: dict[str, Any], check: Checks) -> None:
    """The case's expectations, as compose_api.environments.compliance checks the rows and scalar kinds."""
    for expectation in case["expect"]:
        kind, emitter = expectation["kind"], expectation["emitter"]
        rows = results.get(emitter)
        if not isinstance(rows, list):
            check(False, f"emitter {emitter!r} emitted nothing")
            continue
        if kind == "rows":
            minimum = expectation.get("min", 1)
            check(len(rows) >= minimum, f"{len(rows)} rows from {emitter}, at least {minimum}")
            continue
        if kind != "scalar":
            raise Failure(f"this script checks rows and scalar expectations, not {kind}")
        field, row = expectation.get("field", "result"), expectation.get("row", -1)
        expected = float(expectation["expected"])
        try:
            actual = at(rows[row], field)
        except (IndexError, KeyError, TypeError, ValueError) as e:
            check(False, f"{field} in row {row}: no number ({type(e).__name__}: {e})")
            continue
        close = math.isclose(actual, expected, rel_tol=expectation.get("rel", REL), abs_tol=expectation.get("abs", ABS))
        check(close, f"{field} = {actual!r}, expected {expected!r}")


def check_refused(session: ComposeSession, archive: Path, environment: str | None, check: Checks) -> None:
    try:
        submitted = session.submit(archive, interval=0.5, environment=environment, tags=["vivarium-tyssue-demo"])
    except ApiError as e:
        reason = json.dumps(e.detail) if e.detail else e.message
        check(e.status_code == 400 and "unpickle" in reason, f"submission refused it: {reason[:160]}")
        return
    check(False, f"submission accepted it as simulation {submitted.simulation_database_id}")
    session.cancel_simulation(submitted.simulation_database_id)


def division_document(case_document: dict[str, Any]) -> dict[str, Any]:
    """The case's sheet, with reconnection on and the workspace's CellDivisions regulator dividing cells."""
    document = copy.deepcopy(case_document)
    state = document["state"]
    state["Tyssue"]["interval"] = 0.03125
    state["Tyssue"]["config"]["auto_reconnect"] = {"enabled": True}
    state["Divisions"] = {
        "_type": "process",
        "address": "local:vivarium_tyssue.processes.regulations.CellDivisions",
        "config": {"rate": 4.0, "geom": "SheetGeometry", "crit_area": 2.0, "growth_rate": 1.0},
        "inputs": {"global_time": ["global_time"], "datasets": ["Tissue State"]},
        "outputs": {"behaviors": ["Behaviors"]},
        "interval": 0.03125,
    }
    state["emitter"]["config"]["subsample"] = 32
    return document


def check_divisions(rows: list[Any], check: Checks) -> None:
    """What any run must show. The frames are written as columns, so their rows are positions, which tyssue keeps
    equal to its labels (it renumbers vertices and faces when it adds or removes them)."""
    if not check(len(rows) >= 2, f"{len(rows)} rows emitted, at least 2"):
        return
    try:
        cells = [len(row["tissue"]["face_df"]["area"]) for row in rows]
        check(cells[-1] > cells[0], f"cells divided: {cells[0]} -> {cells[-1]}")
        for row in rows:
            tissue = row["tissue"]
            vertices = range(len(tissue["vert_df"]["x"]))
            faces = range(len(tissue["face_df"]["area"]))
            edges = tissue["edge_df"]
            ends = set(edges["srce"]) | set(edges["trgt"])
            check(
                ends == set(vertices) and set(edges["face"]) == set(faces),
                f"t = {row['global_time']}: {len(edges['srce'])} edges join exactly the {len(vertices)} vertices "
                f"and bound exactly the {len(faces)} faces",
            )
    except (KeyError, TypeError) as e:
        check(False, f"the tissue state is not what EulerSolver writes ({type(e).__name__}: {e})")


def draw(panels: list[tuple[str, Any, Any]], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.collections import LineCollection

    figure, axes = plt.subplots(1, len(panels), figsize=(6 * len(panels), 6))
    for ax, (title, before, after) in zip(axes, panels, strict=True):
        for tissue, colour, width in ((before, "#b8c4bd", 0.8), (after, "#2f7a5b", 1.0)):
            x, y = tissue["vert_df"]["x"], tissue["vert_df"]["y"]
            edges = tissue["edge_df"]
            segments = [((x[s], y[s]), (x[t], y[t])) for s, t in zip(edges["srce"], edges["trgt"], strict=True)]
            ax.add_collection(LineCollection(segments, colors=colour, linewidths=width))
        ax.autoscale()
        ax.set_aspect("equal")
        ax.set_title(title)
        ax.set_axis_off()
    figure.tight_layout()
    figure.savefig(path, dpi=150)


def demonstrate(session: ComposeSession, base_url: str, out: Path, check: Checks) -> None:
    print("1. Introspect")
    environment = introspect(session, base_url, check)

    with tempfile.TemporaryDirectory() as scratch:
        directory = Path(scratch)
        for name, digest in CASE_FILES.items():
            (directory / name).write_bytes(fetch(CASE + name, digest))
        case = yaml.safe_load((directory / "case.yaml").read_text())
        document = json.loads((directory / "document.pbg").read_text())

        print(f"\n2. Run the compliance case, {RELEASE}'s sheet-relaxation")
        relaxed = run(session, pack(directory, document, "relaxation.omex"), case["interval"], environment, out)
        check_case(case, relaxed, check)

        print("\n3. Submit the case with a mesh that pandas would run code from")
        unsafe = {"mesh.h5": fetch(*UNSAFE_MESH)}
        check_refused(session, pack(directory, document, "unsafe.omex", unsafe), environment, check)

        print("\n4. Run CellDivisions on the same sheet")
        divisions = pack(directory, division_document(document), "divisions.omex")
        divided = run(session, divisions, 4.0, environment, out)["emitter"]
        check_divisions(divided, check)

    picture = out / "tyssue-on-compose.png"
    relaxation = relaxed["emitter"]
    draw(
        [
            (
                f"EulerSolver relaxation, t = {relaxation[-1]['global_time']}",
                relaxation[0]["tissue"],
                relaxation[-1]["tissue"],
            ),
            (f"CellDivisions, t = {divided[-1]['global_time']}", divided[0]["tissue"], divided[-1]["tissue"]),
        ],
        picture,
    )
    print(f"\n5. Drew {picture.resolve()} (grey: start, green: end)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run vivarium-tyssue on compose-api and check what comes back.")
    parser.add_argument("--base-url", default="https://compose.cam.uchc.edu")
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "tyssue-on-compose")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    check = Checks()
    session = ComposeSession(args.base_url, token=os.environ.get("COMPOSE_API_TOKEN") or None)
    try:
        demonstrate(session, args.base_url, args.out, check)
    except (CliError, Failure, OSError) as e:  # the service, the network or a result failed: say what, and fail
        what = str(getattr(e, "message", e))
        if isinstance(e, ApiError) and e.detail:
            what += f"\n  {json.dumps(e.detail)}"
        check(False, what)
    print(f"\n{'all checks passed' if not check.failed else f'{check.failed} check(s) failed'}")
    return 1 if check.failed else 0


if __name__ == "__main__":
    sys.exit(main())
