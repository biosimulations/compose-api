"""The closeness score and the comparison of reports (compose_api/sedml/compare.py)."""

import math

from compose_api.sedml.compare import compare, read_report, score
from compose_api.sedml.models import Tolerances

T = Tolerances()


def test_the_platforms_score() -> None:
    # atol = max(1e-3, 100 * 1e-5, 100.01 * 1e-5); the score is |100 - 100.01| / (atol + 1e-4 * 100.01)
    atol = 100.01 * 1e-5
    assert math.isclose(score([0.0, 100.0], [0.0, 100.01], T), 0.01 / (atol + 1e-4 * 100.01), rel_tol=1e-9)
    assert score([1.0, 2.0], [1.0, 2.0], T) == 0.0
    assert score([1.0, 2.0], [1.0, 2.5], T) > 1
    assert score([math.nan, 1.0], [math.nan, 1.0], T) == 0.0
    assert score([math.nan, 1.0], [0.0, 1.0], T) == math.inf
    assert score([1.0], [1.0005], Tolerances(rel_tol=1e-3, abs_tol_min=0.0)) < 1  # looser tolerances


def test_reports_are_compared_label_by_label_and_pair_by_pair() -> None:
    a = read_report("time,A,B\n0.0,1.0,5.0\n1.0,2.0,6.0\n")
    b = read_report("time,A,B\n0.0,1.0,5.0\n1.0,2.0000001,9.0\n")
    c = read_report("time,A\n0.0,1.0\n1.0,2.0\n")  # no B
    result = compare({"copasi": {"r": a}, "tellurium": {"r": b}, "x": {"r": c}}, {"r": ["time", "A", "B"]}, T)
    labels = result["reports"]["r"]["labels"]
    assert labels["A"]["copasi|tellurium"]["close"] is True
    assert labels["B"]["copasi|tellurium"]["close"] is False
    assert labels["B"]["copasi|x"] == {"score": None, "close": None, "missing": ["x"]}
    assert result["reports"]["r"]["worst"]["label"] == "B"
    assert result["close"] is False and result["solvers"] == ["copasi", "tellurium", "x"]


def test_two_agreeing_solvers_are_close_and_lengths_must_match() -> None:
    a = read_report("t,A\n0,1\n1,2\n")
    assert compare({"p": {"r": a}, "q": {"r": a}}, {"r": ["t", "A"]}, T)["close"] is True
    short = read_report("t,A\n0,1\n")
    result = compare({"p": {"r": a}, "q": {"r": short}}, {"r": ["t", "A"]}, T)
    assert result["reports"]["r"]["labels"]["A"]["p|q"] == {"score": None, "close": False, "lengths": [2, 1]}
    assert result["close"] is False
    assert compare({"p": {"r": a}}, {"r": ["t"]}, T)["close"] is False  # one solver is no comparison


def test_references_are_scored_against_each_solver_but_do_not_decide_agreement() -> None:
    a = read_report("t,A\n0,1\n1,2\n")
    far = read_report("t,A\n0,1\n1,3\n")
    result = compare(
        {"p": {"r": a}, "q": {"r": a}}, {"r": ["t", "A"]}, T, references={"biosimulations:run": {"r": far}}
    )
    pairs = result["reports"]["r"]["labels"]["A"]
    assert pairs["p|q"]["close"] is True
    assert pairs["p|biosimulations:run"] == {
        "score": pairs["p|biosimulations:run"]["score"],
        "close": False,
        "reference": True,
    }
    assert result["close"] is True and result["close_to_references"] is False
    assert compare({"p": {"r": a}, "q": {"r": a}}, {"r": ["t"]}, T)["close_to_references"] is None
