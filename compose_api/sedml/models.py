"""What the SED-ML routes take and answer."""

from typing import Any, Literal

from pydantic import BaseModel, Field

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
