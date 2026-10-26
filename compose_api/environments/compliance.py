"""Compliance: what certifies a registry entry in an environment version (docs/plan-environment-composition.md, C3,
step 5).

Two kinds of check, both about the entry's *process classes* (what wraps a library), never the library itself:

- **Generic interface checks**, applied to every component from what its image read back (its interfaces and the type
  tables its entries declare), with no run: :func:`port_findings`. Today one rule, the overwrite bug of
  pbsim_common#21: a step reports a result, so an output port whose type adds (``float``, ``integer``) or appends
  (``list``) an update into the store, rather than replacing it, accumulates its results when the step fires again.
- **Cases**: small composites kept with the entry (``registry/compliance/<entry>/<case>/case.yaml``, the document and
  the files it reads), run in the version, their results checked against expectations: :func:`load_cases`,
  :func:`evaluate`.

An entry is ``tested`` in a version when its cases pass there and no generic check fails (the level a version earns is
recorded per entry and version, EV5); this module decides, the routes and the worker run it (step 5b).
"""

import csv
import io
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

COMPLIANCE_DIR = Path(__file__).parent.parent / "registry" / "compliance"

# --- generic interface checks ----------------------------------------------------------------------------------------

# What a store does with an update, by the leaf type of its port (bigraph-schema's apply): these add it or append it.
_ADDS = {"float", "integer", "number", "int", "length", "time", "concentration", "count", "array"}
_APPENDS = {"list", "set"}
_REPLACES = {"overwrite", "string", "boolean", "enum", "maybe_overwrite", "quote", "const"}
_CONTAINERS = {"map", "tree", "maybe", "wrap"}


def _split(expression: str) -> tuple[str, list[str]]:
    """``map[list[float]]`` -> (``map``, [``list[float]``]); a bare name has no arguments."""
    expression = expression.strip()
    if "[" not in expression or not expression.endswith("]"):
        return expression, []
    head, _, inner = expression.partition("[")
    args, depth, current = [], 0, ""
    for char in inner[:-1]:
        if char == "," and depth == 0:
            args.append(current)
            current = ""
            continue
        depth += {"[": 1, "]": -1}.get(char, 0)
        current += char
    args.append(current)
    return head.strip(), [a.strip() for a in args if a.strip()]


def accumulating_leaves(
    schema: Any, named: dict[str, Any], path: str = "", seen: frozenset[str] = frozenset()
) -> list[str]:
    """Where in ``schema`` (a type expression, or a dict of them) an update adds or appends instead of replacing:
    ``path: type`` for each such leaf. ``named`` resolves type names (the environment's type tables); an unknown name
    or ``any`` is not judged."""
    if isinstance(schema, dict):
        return _dict_leaves(schema, named, path, seen)
    if not isinstance(schema, str):
        return []
    head, args = _split(schema)
    if head in _ADDS or head in _APPENDS:
        return [f"{path or '(port)'}: {schema} ({'adds' if head in _ADDS else 'appends'})"]
    if head in _CONTAINERS:
        return [leaf for a in args[-1:] for leaf in accumulating_leaves(a, named, f"{path}[*]", seen)]
    if head == "tuple":
        return [leaf for i, a in enumerate(args) for leaf in accumulating_leaves(a, named, f"{path}[{i}]", seen)]
    if head in named and head not in seen and head not in _REPLACES:
        return accumulating_leaves(named[head], named, path, seen | {head})
    return []  # replaces (overwrite, string, ...), or not judged (any, an unknown name)


def _dict_leaves(schema: dict[str, Any], named: dict[str, Any], path: str, seen: frozenset[str]) -> list[str]:
    if "_type" in schema:
        return accumulating_leaves(schema["_type"], named, path, seen)
    return [
        leaf
        for key, value in schema.items()
        if not str(key).startswith("_")
        for leaf in accumulating_leaves(value, named, f"{path}.{key}" if path else str(key), seen)
    ]


class Finding(BaseModel):
    """What a generic check found in one component."""

    component: str
    check: str
    severity: Literal["fail", "warn"]
    detail: str


def port_findings(interfaces: dict[str, Any], named: dict[str, Any], module_roots: list[str]) -> list[Finding]:
    """The generic interface checks, over the components of an interface manifest (``pbg-interfaces/1``) under
    ``module_roots``: a step whose output ports accumulate fails ``step-outputs-replace``."""
    findings: list[Finding] = []
    for component in interfaces.get("components", []):
        if not isinstance(component, dict):
            continue  # a malformed read-back judges nothing
        module = str(component.get("module", ""))
        if not any(module == root or module.startswith(root + ".") for root in module_roots):
            continue
        if component.get("kind") != "step":
            continue  # a process's update is a change over its interval: adding is how it is applied
        for port, schema in (component.get("outputs") or {}).items():
            leaves = accumulating_leaves(schema, named, str(port))
            if leaves:
                findings.append(
                    Finding(
                        component=f"{module}.{component.get('name')}",
                        check="step-outputs-replace",
                        severity="fail",
                        detail=f"a step's results must replace, but these accumulate when it fires again: "
                        f"{'; '.join(leaves)}. Declare them overwrite[...]",
                    )
                )
    return findings


# --- cases -----------------------------------------------------------------------------------------------------------


class Expectation(BaseModel):
    """One check of a case's results (the runner's ``.pber``: each emitter's rows). ``emitter`` names the emitter;
    ``field`` the emitted value, a ``numeric_result`` (time, columns, values) unless ``kind`` is ``rows``.

    - ``rows``: the emitter emitted at least ``min`` rows.
    - ``value``: ``column`` at ``time`` (the final row's result when omitted) is ``expected`` within the tolerance.
    - ``reference``: every column of ``reference`` (a CSV in the case, with a time column first) matches the result
      at the reference's times, within the tolerance.
    """

    kind: Literal["rows", "value", "reference"]
    emitter: str
    field: str = "result"
    min: int = 1
    column: str | None = None
    time: float | None = None
    expected: float | None = None
    reference: str | None = None
    rel: float = 1e-6
    abs: float = 1e-9


class Case(BaseModel):
    """A compliance case: a document, the files it reads (by name, as the runner finds them in the archive), how long
    to run it, and what its results must show."""

    name: str = ""
    entry: str = ""
    description: str = ""
    document: str
    files: list[str] = Field(default_factory=list)
    interval: float = 1.0
    expect: list[Expectation] = Field(min_length=1)
    directory: Path | None = Field(default=None, exclude=True)

    def path(self, name: str) -> Path:
        if self.directory is None:
            raise ValueError(f"case {self.name} has no directory")
        return self.directory / name


def load_cases(entry: str, root: Path = COMPLIANCE_DIR) -> list[Case]:
    """An entry's cases, by name (``<root>/<entry>/<case>/case.yaml``); none for an entry that has none yet."""
    cases = []
    for case_file in sorted((root / entry).glob("*/case.yaml")):
        case = Case.model_validate(yaml.safe_load(case_file.read_text()))
        cases.append(
            case.model_copy(update={"name": case_file.parent.name, "entry": entry, "directory": case_file.parent})
        )
    return cases


@dataclass
class Outcome:
    """How one case went: passed, or each expectation it failed."""

    passed: bool
    failures: list[str] = field(default_factory=list)


def _close(actual: float, expected: float, rel: float, absolute: float) -> bool:
    return math.isclose(actual, expected, rel_tol=rel, abs_tol=absolute)


def _result(rows: list[Any], expectation: Expectation) -> dict[str, Any]:
    """The last row's numeric_result for the expectation's field (a step's result is replaced, so the last is it)."""
    for row in reversed(rows):
        value = row.get(expectation.field) if isinstance(row, dict) else None
        if isinstance(value, dict) and value.get("columns"):
            return value
    raise LookupError(f"emitter {expectation.emitter!r} emitted no {expectation.field!r} result")


def _at(result: dict[str, Any], column: str, time: float | None, tolerance: tuple[float, float]) -> float:
    columns = list(result["columns"])
    if column not in columns:
        raise LookupError(f"no column {column!r} (has {', '.join(columns[:12])})")
    times = [float(t) for t in result["time"]]
    row = len(times) - 1 if time is None else next((i for i, t in enumerate(times) if _close(t, time, *tolerance)), -1)
    if row < 0:
        raise LookupError(f"no time {time} in the result")
    return float(result["values"][row][columns.index(column)])


def _check(case: Case, expectation: Expectation, results: dict[str, Any]) -> list[str]:
    rows = results.get(expectation.emitter)
    if not isinstance(rows, list):
        return [f"emitter {expectation.emitter!r} emitted nothing"]
    if expectation.kind == "rows":
        return [] if len(rows) >= expectation.min else [f"{expectation.emitter}: {len(rows)} rows, < {expectation.min}"]
    try:
        result = _result(rows, expectation)
        if expectation.kind == "value":
            return _check_value(expectation, result)
        return _check_reference(case, expectation, result)
    except (LookupError, ValueError, IndexError, KeyError) as e:
        return [f"{expectation.emitter}: {e}"]


def _check_value(expectation: Expectation, result: dict[str, Any]) -> list[str]:
    if expectation.column is None or expectation.expected is None:
        return ["a value expectation needs `column` and `expected`"]
    actual = _at(result, expectation.column, expectation.time, (1e-9, 1e-9))
    if _close(actual, expectation.expected, expectation.rel, expectation.abs):
        return []
    return [f"{expectation.column} at {expectation.time or 'the end'}: {actual}, expected {expectation.expected}"]


def _check_reference(case: Case, expectation: Expectation, result: dict[str, Any]) -> list[str]:
    if expectation.reference is None:
        return ["a reference expectation needs `reference`"]
    table = list(csv.reader(io.StringIO(case.path(expectation.reference).read_text())))
    header, body = table[0], [r for r in table[1:] if r]
    failures = []
    for record in body:
        time = float(record[0])
        for column, text in zip(header[1:], record[1:], strict=False):
            actual = _at(result, column.strip(), time, (1e-9, 1e-9))
            if not _close(actual, float(text), expectation.rel, expectation.abs):
                failures.append(f"{column.strip()} at {time}: {actual}, reference {text}")
    return failures[:20]


def evaluate(case: Case, results: dict[str, Any]) -> Outcome:
    """Check ``results`` (the run's ``.pber``, parsed) against every expectation of ``case``."""
    failures = [f for expectation in case.expect for f in _check(case, expectation, results)]
    return Outcome(passed=not failures, failures=failures)


def results_of(pber: str) -> dict[str, Any]:
    """A ``.pber`` file's results: each emitter's rows."""
    parsed = json.loads(pber)
    return parsed if isinstance(parsed, dict) else {}


_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def case_problems(case: Case) -> list[str]:
    """What keeps a case from running: a missing document or file, or a name the runner could not find by name."""
    problems = []
    for name in [case.document, *case.files, *(e.reference for e in case.expect if e.reference)]:
        if not _SAFE_NAME.match(name):
            problems.append(f"{case.entry}/{case.name}: {name!r} is not a plain file name")
        elif not case.path(name).is_file():
            problems.append(f"{case.entry}/{case.name}: {name} is missing")
    return problems
