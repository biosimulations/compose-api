"""What the SED-ML routes take and answer."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

Severity = Literal["error", "warning", "info"]


class SedmlFinding(BaseModel):
    """A finding of the translation (process-bigraph-lang's `X4xx`) or of the checker on a solver's instance."""

    severity: Severity
    code: str
    message: str
    solver: str | None = None
    task: str | None = None
    path: str | None = None


class SedmlTask(BaseModel):
    """One SED-ML task: its translation's template text, the solvers that accept it, and its reports and plots."""

    sedml: str
    task: str
    name: str
    template: str
    solvers: list[str] = Field(description="the solvers whose instance compiled")
    refused: list[str] = Field(default_factory=list, description="the solvers refused by an error finding")
    reports: list[str] = Field(default_factory=list)
    plots: list[str] = Field(default_factory=list)


class SedmlPreview(BaseModel):
    source: str
    tasks: list[SedmlTask]
    findings: list[SedmlFinding]


class Tolerances(BaseModel):
    """The platform's closeness score: close when `max |a-b| / (atol + rtol*|b|) < 1`, with
    `atol = max(abs_tol_min, max|a|*abs_tol_scale, max|b|*abs_tol_scale)` (docs/plan-sedml.md, D4)."""

    rel_tol: float = Field(default=1e-4, gt=0)
    abs_tol_min: float = Field(default=1e-3, ge=0)
    abs_tol_scale: float = Field(default=1e-5, ge=0)


class ComparisonMember(BaseModel):
    solver: str
    simulation_id: int
    status: str | None = None


class Comparison(BaseModel):
    """One SED-ML task run on several solvers. `result` is filled once every member has finished: per report and
    data set label, each solver pair's score and whether it is close."""

    comparison_id: int
    created_at: str | None = None
    name: str
    source: str
    sedml: str
    task: str
    status: Literal["running", "complete", "incomplete"]
    settings: dict[str, Any]
    members: list[ComparisonMember]
    result: dict[str, Any] | None = None
    close: bool | None = Field(default=None, description="every compared data set close, every member completed")


class ComparisonPage(BaseModel):
    comparisons: list[Comparison]
    total: int
    next_offset: int | None = None


class SedmlRunResult(BaseModel):
    comparisons: list[Comparison]
    findings: list[SedmlFinding]


class ComparisonSeries(BaseModel):
    """One report's columns from each member (by solver) and each reference (by origin), for overlays."""

    report: str
    labels: list[str]
    solvers: dict[str, dict[str, list[float | None]]]
    references: dict[str, dict[str, list[float | None]]]


#: A BioSimulators simulator as biosim's /verify takes it: ``name`` or ``name:version``.
SIMULATOR_PATTERN = r"^[a-z0-9][a-z0-9_-]*(:[A-Za-z0-9_.+-]+)?$"


class VerifyRequest(BaseModel):
    """Which BioSimulators simulators to verify a comparison with (docs/plan-verify-oracle.md, V4)."""

    simulators: list[Annotated[str, StringConstraints(pattern=SIMULATOR_PATTERN)]] | None = Field(
        default=None,
        min_length=2,
        max_length=10,
        description="`name` or `name:version`; by default the service's (amici, copasi, pysces, tellurium, vcell)",
    )


class Verification(BaseModel):
    """One request to biosim's /verify API about a comparison: the archive the comparison ran, on BioSimulators'
    simulators (docs/plan-verify-oracle.md). Once `completed`, each simulator's reports are a reference on the
    comparison, and `verify_close` says whether the simulators agree with each other."""

    verification_id: int
    comparison_id: int
    state: Literal["requested", "submitted", "completed", "failed"]
    simulators: list[str]
    workflow_id: str | None = None
    workflow_status: str | None = None
    verify_close: bool | None = Field(default=None, description="BioSimulators' simulators agree on every report")
    references: list[str] = Field(default_factory=list, description="the reference origins it added")
    failed_simulators: list[dict[str, Any]] = Field(
        default_factory=list, description="simulators whose runs at biosimulations.org produced no results"
    )
    attempts: int = 0
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SuiteVerifyResult(BaseModel):
    """Verifications queued for a suite run's comparisons."""

    queued: list[int] = Field(description="comparisons a verification was queued for")
    already: list[int] = Field(description="comparisons with a verification already queued or running")
    running: int = Field(description="comparisons still running, not yet looked at")


class KnownProblem(BaseModel):
    """A known problem of one solver on one source of a suite (docs/plan-known-problems.md): excused in the suite's
    runs numbered below `cleared_run` (every run while it is open). No solver: the whole source is excused."""

    problem_id: int
    suite: str
    source: str
    solver: str | None = None
    category: str = Field(description="what kind of problem, e.g. VCell's fault names (NONINTEGER_STOICH, DELAY)")
    reason: str
    seen_run: int | None = Field(default=None, description="the suite run it was first seen in")
    marked_by: str
    marked_at: str | None = None
    cleared_run: int | None = Field(default=None, description="the suite run that showed it fixed")
    cleared_by: str | None = None
    cleared_at: str | None = None


_CATEGORY = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
_REASON = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class KnownProblemMark(BaseModel):
    """A known problem to record: the source and solver (none for the whole source), and why."""

    source: str
    solver: str | None = None
    category: _CATEGORY
    reason: _REASON
    seen_run: int | None = Field(default=None, description="the suite run it was first seen in")


class KnownProblemEdit(BaseModel):
    """A new category or reason for a known problem; what is not given stays."""

    category: _CATEGORY | None = None
    reason: _REASON | None = None


class KnownProblemClear(BaseModel):
    """Clear a known problem: the suite run that shows it fixed. Runs before it still excuse it."""

    run: int
