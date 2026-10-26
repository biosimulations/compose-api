"""Structural alarms for additions to the hand-written HTTP boundary."""

import ast
import importlib.resources
import json
from pathlib import Path

from tests.client.test_ext_security import SUBMISSIONS


def test_every_post_has_an_explicit_submission_policy() -> None:
    spec = json.loads(importlib.resources.files("compose_api_client").joinpath("openapi.json").read_text())
    posts = {path for path, methods in spec["paths"].items() if "post" in methods}
    # POSTs that change nothing, or set a state, so a retry is safe (replayable)
    idempotent_operations = {
        "preview-sedml",
        "preview-environment-version",
        "retire-environment-version",
        "inspect-environment-version",
        "clear-suite-problem",  # a second clear answers 409
    }
    idempotent = {
        path
        for path, methods in spec["paths"].items()
        if methods.get("post", {}).get("operationId") in idempotent_operations
    }
    assert len(idempotent) == len(idempotent_operations)
    assert posts - idempotent == {path for _, path, _, _ in SUBMISSIONS}


def test_only_generated_code_constructs_bearer_headers() -> None:
    root = Path(str(importlib.resources.files("compose_api_client")))
    violations = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if relative.parts[0] in {"api", "models"} or str(relative) in {"client.py", "errors.py", "types.py"}:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            # Also catches f-strings, mixed quote styles and case variants.
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and (node.value.lower().startswith("bearer ") or node.value.lower() == "authorization")
            ):
                violations.append(f"{relative}:{node.lineno}")
    assert violations == []
