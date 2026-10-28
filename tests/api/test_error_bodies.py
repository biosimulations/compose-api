"""No `Any` in the API's types (compose_api/api/errors.py): every response the spec declares has a body schema, so
the client generated from it types every operation's answer; a response with a description alone is typed `Any` by
openapi-python-client, and `Any` in a union makes the whole return type `Any` to a type checker."""

import ast
from pathlib import Path
from typing import Any

from compose_api.api.main import app

CLIENT_API = Path(__file__).resolve().parents[2] / "clients" / "python" / "compose_api_client" / "api"


def _has_body(response: dict[str, Any]) -> bool:
    """A content type whose schema names a type, a model, or a union of them."""
    content: dict[str, dict[str, dict[str, object]]] = response.get("content") or {}
    return any({"type", "$ref", "anyOf"} & set(media.get("schema", {})) for media in content.values())


def test_every_response_declares_its_body() -> None:
    untyped = [
        f"{op['operationId']} {code}"
        for methods in app.openapi()["paths"].values()
        for op in methods.values()
        for code, response in op["responses"].items()
        if not _has_body(response)
    ]
    assert untyped == [], "declare a body (`error(...)` in compose_api/api/errors.py, or a model) for: " + ", ".join(
        untyped
    )


def test_no_generated_operation_returns_any() -> None:
    found = [
        f"{path.relative_to(CLIENT_API)}::{node.name} -> {ast.unparse(node.returns)}"
        for path in sorted(CLIENT_API.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name != "_get_kwargs"  # the generator's own request arguments, not an answer
        and node.returns is not None
        and "Any" in ast.unparse(node.returns)
    ]
    assert found == [], "\n".join(found)
