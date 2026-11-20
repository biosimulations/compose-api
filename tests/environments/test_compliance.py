"""Compliance (docs/plan-environment-composition.md, step 5a): the generic check that a step's results replace, the
cases kept with an entry, and their evaluation against a run's results."""

import json
import math
from pathlib import Path
from typing import Any

import pytest

from compose_api.environments import compliance
from compose_api.environments.compliance import (
    Case,
    accumulating_leaves,
    evaluate,
    import_findings,
    load_cases,
    port_findings,
)

NUMERIC_RESULT = {"time": "list[float]", "columns": "list[string]", "values": "list[list[float]]"}
FIXED = {
    "time": "overwrite[list[float]]",
    "columns": "overwrite[list[string]]",
    "values": "overwrite[list[list[float]]]",
}


@pytest.mark.parametrize(
    ("schema", "leaves"),
    [
        ("float", ["p: float (adds)"]),
        ("overwrite[float]", []),
        ("map[float]", ["p[*]: float (adds)"]),
        ("map[overwrite[float]]", []),
        ("list[float]", ["p: list[float] (appends)"]),
        ("array", ["p: array (adds)"]),
        ("string", []),
        ("any", []),  # not judged
        ("unknown_name", []),  # not judged
        ("tuple[float,overwrite[float]]", ["p[0]: float (adds)"]),
        ({"a": "overwrite[float]", "b": "integer"}, ["p.b: integer (adds)"]),
        ({"_type": "overwrite[list[float]]"}, []),
    ],
)
def test_what_accumulates_is_found_where_it_does(schema: object, leaves: list[str]) -> None:
    assert accumulating_leaves(schema, {}, "p") == leaves


def test_named_types_are_resolved_and_a_cycle_ends() -> None:
    named = {"numeric_result": NUMERIC_RESULT, "results": "map[numeric_result]", "loop": "map[loop]"}
    assert accumulating_leaves("results", named, "r") == [
        "r[*].time: list[float] (appends)",
        "r[*].columns: list[string] (appends)",
        "r[*].values: list[list[float]] (appends)",
    ]
    assert accumulating_leaves("results", {**named, "numeric_result": FIXED}, "r") == []
    assert accumulating_leaves("loop", named, "l") == []


def _manifest() -> dict[str, object]:
    return {
        "components": [
            {"name": "UTC", "kind": "step", "module": "pkg.steps", "outputs": {"result": "numeric_result"}},
            {"name": "Ok", "kind": "step", "module": "pkg.steps", "outputs": {"data": "overwrite[map[float]]"}},
            {"name": "Ode", "kind": "process", "module": "pkg.procs", "outputs": {"x": "map[float]"}},  # deltas
            {"name": "Other", "kind": "step", "module": "elsewhere", "outputs": {"y": "float"}},  # another entry's
        ]
    }


def test_a_step_whose_results_accumulate_fails_and_a_process_does_not() -> None:
    (finding,) = port_findings(_manifest(), {"numeric_result": NUMERIC_RESULT}, ["pkg"])
    assert (finding.component, finding.check, finding.severity) == ("pkg.steps.UTC", "step-outputs-replace", "fail")
    assert "result.time: list[float] (appends)" in finding.detail and "overwrite[" in finding.detail
    assert port_findings(_manifest(), {"numeric_result": FIXED}, ["pkg"]) == []


def test_a_module_that_does_not_import_and_a_missing_solver_class_fail() -> None:
    """registry_env@6 (2026-11-06): python-dateutil 4 dropped six, tellurium imports it, and pbsim_common.simulators
    did not import, so no solver class was in the image."""
    six = "ModuleNotFoundError: No module named 'six'"
    broken = {
        "errors": [
            {"module": "pbsim_common.simulators", "error": six},
            {"module": "pbsim_common.simulators", "error": six},  # the describe script reports it once per root
            {"module": "elsewhere.plugin", "error": "ImportError: x"},  # not under the version's roots
        ],
        "components": [{"module": "pbsim_common.comparison", "name": "MSEComparison", "kind": "step"}],
    }
    (finding,) = import_findings(broken, ["pbsim_common"], "registry_env")
    assert (finding.component, finding.check, finding.severity) == ("pbsim_common.simulators", "module-imports", "fail")
    assert finding.detail == f"it does not import in the image: {six}"
    # no error recorded, yet the solvers' classes are missing: each solver says so
    missing = import_findings({"components": broken["components"]}, ["pbsim_common"], "registry_env")
    assert {(f.component.rsplit(".", 1)[1], f.check) for f in missing} == {
        ("CopasiUTCStep", "solver-provided"),
        ("TelluriumUTCStep", "solver-provided"),
        ("VCellUTCStep", "solver-provided"),
    }
    # registry_env@1's image provides them all; another environment's solvers are not its business
    manifest = json.loads((Path(__file__).parents[1] / "fixtures/resources/registry_env@1.interfaces.json").read_text())
    assert [
        f for f in import_findings(manifest, ["pbsim_common"], "registry_env") if f.check == "solver-provided"
    ] == []
    assert import_findings({"components": []}, ["pbsim_common"], "viva-pde-particle") == []


def test_registry_env_at_1_fails_exactly_the_steps_pbsim_common_21_fixes_and_its_tools() -> None:
    """registry_env@1's image (pbest's, before pbsim_common#21), as its committed manifest recorded it."""
    manifest = json.loads((Path(__file__).parents[1] / "fixtures/resources/registry_env@1.interfaces.json").read_text())
    roots = ["pbsim_common", "biosim_toolkit"]
    before = {f.component.rsplit(".", 1)[1] for f in port_findings(manifest, {"numeric_result": NUMERIC_RESULT}, roots)}
    after = {f.component.rsplit(".", 1)[1] for f in port_findings(manifest, {"numeric_result": FIXED}, roots)}
    assert {"CopasiUTCStep", "TelluriumUTCStep", "VCellUTCStep"} <= before - after
    assert after == {"ComparisonTool", "MSEComparison", "StatsTool", "SumOfSquaresTool"}  # still accumulating
    assert not {"DataGenerators", "Report", "Plots"} & before  # biosim-toolkit's steps already overwrite


def test_pbsim_commons_cases_are_complete() -> None:
    cases = load_cases("pbsim-common")
    assert {c.name for c in cases} >= {"copasi-phase-cycle", "tellurium-phase-cycle"}
    for case in cases:
        assert compliance.case_problems(case) == []
    assert load_cases("no-such-entry") == []


@pytest.mark.parametrize(
    ("entry", "case"),
    [
        ("viva-copasi", "phase-cycle-copasi-report"),
        ("viva-tellurium", "phase-cycle-copasi-report"),
        ("viva-tellurium", "stimulus-through-port"),
        ("viva-cobra", "textbook-fba-optimum"),
        ("viva-cobra", "textbook-dfba-process"),
        ("viva-maboss", "switching-analytic-oracle"),
        ("viva-nfsim", "flagella-seeded"),
        ("viva-smoldyn", "seeded-decay-2d"),
        ("viva-fenics", "poisson-quadratic-mms"),
        ("vivarium-tyssue", "sheet-relaxation"),
        ("viva-pde-particle", "region-mean-closed-form"),
    ],
)
def test_onboarded_cases_load_and_their_files_exist(entry: str, case: str) -> None:
    """Each onboarded entry's case is found by name, and its document is present and self-contained."""
    (found,) = [c for c in load_cases(entry) if c.name == case]
    assert found.entry == entry
    assert compliance.case_problems(found) == []


def _result(scale: float = 1.0) -> dict[str, object]:
    return {
        "emitter": [
            {"result": {"time": [0.0, 1.0, 2.0], "columns": ["A", "B"], "values": [[0, 5], [1, 6], [2 * scale, 7]]}}
        ]
    }


def _case(tmp_path: Path, *expect: dict[str, object]) -> Case:
    (tmp_path / "reference.csv").write_text("time,A,B\n0,0,5\n2,2,7\n")
    return Case.model_validate({"document": "d.pbg", "expect": list(expect), "directory": tmp_path, "name": "c"})


def test_a_case_passes_or_says_what_failed(tmp_path: Path) -> None:
    case = _case(
        tmp_path,
        {"kind": "rows", "emitter": "emitter", "min": 1},
        {"kind": "value", "emitter": "emitter", "column": "A", "expected": 2.0, "rel": 1e-9},
        {"kind": "value", "emitter": "emitter", "column": "B", "time": 1.0, "expected": 6.0},
        {"kind": "reference", "emitter": "emitter", "reference": "reference.csv", "rel": 1e-9},
    )
    assert evaluate(case, _result()).passed
    off = evaluate(case, _result(scale=1.5))
    assert not off.passed
    assert off.failures == ["A at the end: 3.0, expected 2.0", "A at 2.0: 3.0, reference 2"]
    nothing = evaluate(case, {})
    assert not nothing.passed and nothing.failures[0] == "emitter 'emitter' emitted nothing"
    missing = evaluate(
        _case(tmp_path, {"kind": "value", "emitter": "emitter", "column": "Z", "expected": 1}), _result()
    )
    assert "no column 'Z'" in missing.failures[0]


def test_a_case_names_plain_files_that_exist(tmp_path: Path) -> None:
    case = _case(tmp_path, {"kind": "rows", "emitter": "emitter"}).model_copy(
        update={"files": ["../escape.sbml", "absent.sbml"], "entry": "e"}
    )
    problems = compliance.case_problems(case)
    assert "e/c: '../escape.sbml' is not a plain file name" in problems
    assert "e/c: d.pbg is missing" in problems and "e/c: absent.sbml is missing" in problems


def test_viva_basic_processes_case_checks_plain_numbers() -> None:
    """Its stores are floats, not a numeric_result: `scalar` expectations, here against the rows compose-api's runner
    emitted for this document on 2026-10-26 (x: 1 + 2 per step; y = 3x + 1; one tick per step)."""
    (case,) = [c for c in load_cases("viva-basic-processes") if c.name == "intervention-and-expression"]
    assert compliance.case_problems(case) == []
    rows = [{"x": 1.0 + 2 * t, "y": 3 * (1.0 + 2 * t) + 1, "tick": t, "global_time": float(t)} for t in range(6)]
    assert evaluate(case, {"emitter": rows}).passed
    wrong = [*rows[:-1], {**rows[-1], "y": 33.0}]
    outcome = evaluate(case, {"emitter": wrong})
    assert not outcome.passed and outcome.failures == ["emitter.y in row -1: 33.0, expected 34.0"]
    missing = evaluate(case, {"emitter": [{"x": 1.0}]})
    assert any("no number" in f for f in missing.failures)


def test_viva_basic_processes_time_series_case_checks_the_hold() -> None:
    """TimeSeriesStep replays samples at t = 0, 30, 60, 90 with a zero-order hold, and a Step reads each at its instant
    (y = 2c); after the last sample the last value holds. Rows by hand."""
    (case,) = [c for c in load_cases("viva-basic-processes") if c.name == "time-series-replay"]
    assert compliance.case_problems(case) == []
    held = [0.0, 2.5, 1.5, 0.5, 0.5, 0.5]
    rows = [{"t": 30.0 * k, "c": c, "y": 2 * c, "global_time": 30.0 * k} for k, c in enumerate(held)]
    assert evaluate(case, {"emitter": rows}).passed
    late = [{**row, "c": held[max(k - 1, 0)], "y": 2 * held[max(k - 1, 0)]} for k, row in enumerate(rows)]
    assert not evaluate(case, {"emitter": late}).passed  # one interval late: the hold read before the sample


def test_viva_pde_particles_case_reads_an_ensembles_values_by_path() -> None:
    """Its emitter records each seed's values as lists, so `scalar` reads `values.2.0`: a path into lists and maps
    (composition 7c-4). The rows are what compose-api's runner emitted for this document in the registry_env@5 +
    viva-pde-particle environment on 2026-10-27, identical to its prebuilt image's."""
    (case,) = [c for c in load_cases("viva-pde-particle") if c.name == "fokker-planck-ensemble"]
    assert compliance.case_problems(case) == []
    values = [[0.07137369415367853, 0.0004004746655585104], [0.0, 0.0],
              [0.09234150979599469, 0.0020975747341526988], [0.0, 0.0]]  # fmt: skip
    rows = [{"seeds": [], "values": []}, {"seeds": [1, 2, 3, 4], "values": values}]
    assert evaluate(case, {"emitter": rows}).passed
    off = [rows[0], {"seeds": [1, 2, 3, 4], "values": [values[0], values[1], [0.09, 0.002], values[3]]}]
    outcome = evaluate(case, {"emitter": off})
    assert not outcome.passed and any(f.startswith("emitter.values.2.0 in row -1: 0.09") for f in outcome.failures)
    short = evaluate(case, {"emitter": [rows[0], {"seeds": [1], "values": [values[0]]}]})
    assert any("no number (IndexError" in f for f in short.failures)
    # the document names its emitter fully qualified (D7c.2), never viva-pde-particle's own short `ram-emitter`
    document = json.loads(case.path(case.document).read_text())
    assert document["state"]["emitter"]["address"] == "local:process_bigraph.emitter.RAMEmitter"


def test_viva_pde_particles_region_mean_case_holds_its_closed_forms() -> None:
    """RegionMean (viva-pde-particle#70) over FVReactionDiffusion's fields. The rows are what compose-api's runner
    emitted for this document on 2026-11-18, on process-bigraph 1.9.1 with viva-pde-particle at 25e8a05. Each wrong
    reduction fails, so the case tells them apart:
    - a node of 7 uM inside the mask: 57/26;
    - the mask transposed: 5.2, which the non-square grid exposes;
    - a plain node average: 876/143;
    - the exact exponential in place of the scheme's explicit Euler: 0.5 e^-0.1."""
    (case,) = [c for c in load_cases("viva-pde-particle") if c.name == "region-mean-closed-form"]
    assert compliance.case_problems(case) == []
    whole = 715 / 120
    rows: list[dict[str, Any]] = [
        {"inner": {"B": 2.0, "A": 0.5}, "whole": {"B": whole}, "global_time": 0.0},
        {"inner": {"B": 2.0, "A": 0.4523960735568535}, "whole": {"B": whole}, "global_time": 1.0},
        {"inner": {"B": 2.0, "A": 0.40932441473931513}, "whole": {"B": whole}, "global_time": 2.0},
    ]
    assert evaluate(case, {"emitter": rows}).passed

    def failures(field: str, value: float) -> list[str]:
        store, species = field.split(".")
        bad = [rows[0], *({**r, store: {**r[store], species: value}} for r in rows[1:])]
        return evaluate(case, {"emitter": bad}).failures

    assert any(f.startswith("emitter.inner.B in row 1: 2.19") for f in failures("inner.B", 57 / 26))
    assert any(f.startswith("emitter.inner.B in row 1: 5.2") for f in failures("inner.B", 5.2))
    assert any(f.startswith("emitter.whole.B in row 2: 6.12") for f in failures("whole.B", 876 / 143))
    assert any(f.startswith("emitter.inner.A in row 1: 0.45241") for f in failures("inner.A", 0.5 * math.exp(-0.1)))
    document = json.loads(case.path(case.document).read_text())
    addresses = {node["address"] for node in document["state"].values() if isinstance(node, dict) and "address" in node}
    assert addresses == {
        "local:viva_pde_particle.processes.fv_reaction_diffusion.FVReactionDiffusion",
        "local:viva_pde_particle.steps.transfer.RegionMean",
        "local:process_bigraph.emitter.RAMEmitter",
    }


def test_an_accepted_failure_stays_on_the_record_and_refuses_nothing() -> None:
    """A failure the component's entry accepts is marked with the entry's reason and no longer refuses it; another
    check's failure, or the same check on another component, still does."""
    from compose_api.environments.compliance import Finding, accept, refuses
    from compose_api.registry.manifest import RegistryEntry

    entry = RegistryEntry.model_validate({
        "id": "pkg", "package": "pkg", "source": "https://example.org", "version": "1", "level": "tested",
        "module_roots": ["pkg"], "install": {"git": "https://github.com/o/pkg", "commit": "a" * 40},
        "accepted_findings": [{"component": "pkg.Gated", "check": "step-outputs-replace", "reason": "gated",
                               "evidence": "tests/test_gate.py"}],
    })  # fmt: skip
    findings = [
        Finding(component="pkg.Gated", check="step-outputs-replace", severity="fail", detail="adds"),
        Finding(component="pkg.Gated", check="module-imports", severity="fail", detail="no module"),
        Finding(component="pkg.Other", check="step-outputs-replace", severity="fail", detail="adds"),
    ]
    marked = [f.model_dump() for f in accept(findings, [entry])]
    assert [f["accepted"] for f in marked] == ["gated", None, None]
    assert [refuses(f) for f in marked] == [False, True, True]
