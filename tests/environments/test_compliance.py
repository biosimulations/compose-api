"""Compliance (docs/plan-environment-composition.md, step 5a): the generic check that a step's results replace, the
cases kept with an entry, and their evaluation against a run's results."""

import json
from pathlib import Path

import pytest

from compose_api.environments import compliance
from compose_api.environments.compliance import Case, accumulating_leaves, evaluate, load_cases, port_findings

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


def test_registry_env_today_fails_exactly_the_steps_pbsim_common_21_fixes_and_its_tools() -> None:
    manifest = json.loads(
        (Path(compliance.__file__).parent.parent / "registry/manifests/registry_env.json").read_text()
    )
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
