"""The bodies of the API's error responses, declared on every route so the OpenAPI spec, and the client generated from
it, type each one. A response declared with a description alone is typed ``Any`` by openapi-python-client, and ``Any``
in a union makes the whole return type ``Any`` to a type checker; `tests/api/test_error_bodies.py` fails on one.

An ``HTTPException`` writes ``{"detail": ...}``. Its detail is a message everywhere except where a submission is refused
for its contents: those routes raise one of the structured details below, built from these models so what is raised
and what is declared cannot drift apart."""

from typing import Any

from pydantic import BaseModel

from compose_api.registry.validation import AddressViolation
from compose_api.sedml.models import SedmlFinding


class ErrorDetail(BaseModel):
    """An error, as ``HTTPException(status_code, detail="...")`` writes it."""

    detail: str


class Rejection(BaseModel):
    """A document refused at submission: the addresses it may not use, and why (`registry.validation`)."""

    message: str
    violations: list[AddressViolation]


class NoTaskAccepted(BaseModel):
    """A SED-ML archive none of whose tasks any solver accepted, with the translation's findings."""

    message: str
    findings: list[SedmlFinding]


class SubmissionError(BaseModel):
    """A run refused: a message, or the refused addresses."""

    detail: str | Rejection


class SedmlRunError(BaseModel):
    """A SED-ML run refused: a message, the refused addresses, or the findings when no task was accepted."""

    detail: str | Rejection | NoTaskAccepted


class ValidationIssue(BaseModel):
    """One of FastAPI's request-validation errors (its ``HTTPValidationError`` items)."""

    loc: list[str | int]
    msg: str
    type: str


class UnprocessableError(BaseModel):
    """A 422 a route raises itself (a message), or FastAPI's validation of the request (a list of issues)."""

    detail: str | list[ValidationIssue]


def error(description: str, model: type[BaseModel] = ErrorDetail) -> dict[str, Any]:
    """A route's ``responses`` entry for an error: its body's model and what it means."""
    return {"model": model, "description": description}


# what /sedml/run, and the source shortcuts that run an archive the same way (sources.py), answer when they refuse it
SEDML_REFUSED = error(
    "Not an archive, an unknown solver, a bad tag or version: `detail` is a message. Processes the registry does not "
    "allow: `detail` has a `message` and `violations`. No task any solver accepted: a `message` and the `findings`.",
    SedmlRunError,
)
