"""Comparing the reports of one SED-ML task run on several solvers (docs/plan-sedml.md, D4): the platform's closeness
score per data set label, for every pair of solvers. Plain functions over parsed CSVs; `service.py` reads the files."""

import csv
import io
import math
from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any

from compose_api.sedml.models import Tolerances

Series = list[float]


def read_report(text: str) -> dict[str, Series]:
    """A report CSV (biosim-toolkit's `Report`: a header of labels, a row per time point) as columns by label."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {}
    header, body = rows[0], rows[1:]
    return {label: [_float(r[i]) for r in body if i < len(r)] for i, label in enumerate(header)}


def score(a: Sequence[float], b: Sequence[float], tolerances: Tolerances) -> float:
    """`max |a-b| / (atol + rtol*|b|)`, `atol = max(abs_tol_min, max|a|*scale, max|b|*scale)`; below 1 is close.
    NaN where both are NaN is equal; NaN against a number is infinitely far."""
    finite_a = [abs(x) for x in a if math.isfinite(x)] or [0.0]
    finite_b = [abs(x) for x in b if math.isfinite(x)] or [0.0]
    atol = max(
        tolerances.abs_tol_min, max(finite_a) * tolerances.abs_tol_scale, max(finite_b) * tolerances.abs_tol_scale
    )
    worst = 0.0
    for x, y in zip(a, b, strict=True):
        if math.isnan(x) and math.isnan(y):
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            return math.inf
        worst = max(worst, abs(x - y) / (atol + tolerances.rel_tol * abs(y)))
    return worst


def compare(
    reports: Mapping[str, Mapping[str, Mapping[str, Series]]],
    labels: Mapping[str, Sequence[str]],
    tolerances: Tolerances,
) -> dict[str, Any]:
    """`reports[solver][report][label]`; `labels[report]` the labels the SED-ML asks for. Per report and label, each
    solver pair's score (`a|b`) and whether it is close; a label a solver lacks, or columns of different lengths, are
    reported as such, never scored. `close` is every pair of every label close."""
    solvers = sorted(reports)
    out: dict[str, Any] = {"solvers": solvers, "reports": {}}
    all_close = len(solvers) >= 2
    for report_id, report_labels in labels.items():
        entry: dict[str, Any] = {}
        for label in report_labels:
            pairs: dict[str, Any] = {}
            for a, b in combinations(solvers, 2):
                col_a = reports[a].get(report_id, {}).get(label)
                col_b = reports[b].get(report_id, {}).get(label)
                if col_a is None or col_b is None:
                    missing = [s for s, c in ((a, col_a), (b, col_b)) if c is None]
                    pairs[f"{a}|{b}"] = {"score": None, "close": None, "missing": missing}
                    continue
                if len(col_a) != len(col_b):
                    pairs[f"{a}|{b}"] = {"score": None, "close": False, "lengths": [len(col_a), len(col_b)]}
                    all_close = False
                    continue
                s = score(col_a, col_b, tolerances)
                pairs[f"{a}|{b}"] = {"score": _json_float(s), "close": s < 1}
                all_close = all_close and s < 1
            entry[label] = pairs
        scored = [(p["score"], label) for label, ps in entry.items() for p in ps.values() if p["score"] is not None]
        worst = max(scored, default=(None, None), key=lambda t: t[0] if t[0] is not None else -1.0)
        out["reports"][report_id] = {"labels": entry, "worst": {"label": worst[1], "score": worst[0]}}
    out["close"] = all_close
    return out


def _float(text: str) -> float:
    try:
        return float(text) if text != "" else math.nan
    except ValueError:
        return math.nan


def _json_float(value: float) -> float | str:
    return value if math.isfinite(value) else "inf"
