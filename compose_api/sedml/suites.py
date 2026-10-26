"""Regression and reproducibility suites (docs/plan-sedml.md, phase 6): `examples/<name>/suite.yaml`, reviewed lists of
SED-ML sources run on several solvers. A suite run is one comparison per source and task, labelled with the suite and
the run's number; it checks agreement (the solvers with each other and with references) and, once a run is accepted
as the suite's baseline, regression (each solver against its own result in the baseline run)."""

import functools
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from compose_api.config import REPO_ROOT
from compose_api.sedml.models import Tolerances

SUITES_DIR = Path(REPO_ROOT) / "examples"


class Suite(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str
    sources: list[str] = Field(min_length=1)
    solvers: list[str] | None = None
    tolerances: Tolerances = Field(default_factory=Tolerances)
    baseline: int | None = Field(default=None, description="the accepted suite run that later runs are compared with")
    verify: Literal["none", "failing", "all"] = Field(
        default="none",
        description="check comparisons against biosim's /verify once they finish: those that differ, are incomplete "
        "or have no reference that agrees (failing), or every one (docs/plan-verify-oracle.md, D3)",
    )

    @field_validator("sources")
    @classmethod
    def _sources(cls, sources: list[str]) -> list[str]:
        for s in sources:
            kind, _, ident = s.partition(":")
            if kind not in ("biomodels", "biosimulations") or not ident:
                raise ValueError(f"{s!r}: a source is biomodels:<id> or biosimulations:<project>")
        return sources


@functools.cache
def load_suites(directory: Path = SUITES_DIR) -> dict[str, Suite]:
    suites: dict[str, Suite] = {}
    for path in sorted(directory.glob("*/suite.yaml")):
        suite = Suite.model_validate(yaml.safe_load(path.read_text()))
        if suite.name != path.parent.name:
            raise ValueError(f"{path}: name {suite.name!r} differs from its directory")
        suites[suite.name] = suite
    return suites


def suite(name: str) -> Suite | None:
    return load_suites().get(name)
