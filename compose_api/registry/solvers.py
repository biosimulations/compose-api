"""Solvers (registry/solvers.yaml): which implementation of a role a SED-ML run uses, in which environment, with which
algorithms (docs/plan-sedml.md, "Concepts"). process-bigraph-lang's `sedml translate` takes them as data
(`process_bigraph_lang.v2.sedml_translate.solvers_from`)."""

import functools
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

SOLVERS_PATH = Path(__file__).parent / "solvers.yaml"


class Solver(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    name: str
    role: Literal["TimeCourseSolver"]
    environment: str
    address: str = Field(pattern=r"^local:[A-Za-z_][\w.]*\.[A-Za-z_]\w*$")
    algorithms: list[str] = Field(min_length=1, description="KiSAO terms it implements, its default first")
    provides: list[str] = Field(default_factory=lambda: ["species"])

    def as_translation_data(self) -> dict[str, object]:
        """The form `sedml translate` takes (`solvers_from`)."""
        return {"id": self.id, "address": self.address, "algorithms": self.algorithms, "provides": self.provides}


class SolversFile(BaseModel):
    solvers: list[Solver]

    @model_validator(mode="after")
    def _unique(self) -> "SolversFile":
        ids = [s.id for s in self.solvers]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"solver ids appear more than once: {duplicates}")
        return self


@functools.cache
def load_solvers(path: Path = SOLVERS_PATH) -> SolversFile:
    return SolversFile.model_validate(yaml.safe_load(path.read_text()))


def solver(solver_id: str) -> Solver | None:
    return next((s for s in load_solvers().solvers if s.id == solver_id), None)
