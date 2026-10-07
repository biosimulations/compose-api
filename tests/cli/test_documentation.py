"""docs/cli.md describes the CLI that actually ships: every command, variable, exit code and built-in value."""

import argparse
import inspect
import re
from pathlib import Path

import pytest
import yaml

from compose_api.cli import errors
from compose_api.cli.config import _ENV_FIELDS, BUILTIN_PROFILES
from compose_api.cli.errors import CliError, ExitCode
from compose_api.cli.main import build_parser
from compose_api.config import REPO_ROOT

ROOT = Path(REPO_ROOT)
CLI_DOC = (ROOT / "docs" / "cli.md").read_text()


def _commands(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Every leaf command of the parser, such as ("auth", "login")."""
    found: list[tuple[str, ...]] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                found.extend(_commands(child, (*prefix, name)) or [(*prefix, name)])
    return found


@pytest.mark.parametrize("command", _commands(build_parser()), ids=" ".join)
def test_every_command_is_documented(command: tuple[str, ...]) -> None:
    assert f"compose-api {' '.join(command)}" in CLI_DOC


@pytest.mark.parametrize("variable", sorted(_ENV_FIELDS))
def test_every_environment_variable_is_documented(variable: str) -> None:
    assert f"`{variable}`" in CLI_DOC


def test_every_exit_code_and_category_is_documented() -> None:
    table = CLI_DOC[CLI_DOC.index("| Exit | Category | Meaning |") :]
    for code in ExitCode:
        assert re.search(rf"^\| {int(code)} \|", table, re.MULTILINE), f"exit {int(code)} is missing"
    categories = {
        cls.category
        for _, cls in inspect.getmembers(errors, inspect.isclass)
        if issubclass(cls, CliError) and cls is not CliError
    }
    for category in [*categories, "internal"]:
        assert f"`{category}`" in table, f"category {category} is missing"


@pytest.mark.parametrize("name", list(BUILTIN_PROFILES))
def test_the_built_in_profiles_are_documented_as_they_are(name: str) -> None:
    profile = BUILTIN_PROFILES[name]
    row = next(line for line in CLI_DOC.splitlines() if line.startswith(f"| `{name}`"))
    for field in ("api_base_url", "auth0_audience", "auth0_client_id"):
        assert f"`{profile[field]}`" in row, f"{name} {field}"
    for field in ("auth0_domain", "database_connection", "google_connection"):
        assert f"`{profile[field]}`" in CLI_DOC


def test_the_cli_page_is_published_and_linked() -> None:
    navigation = yaml.safe_load((ROOT / "mkdocs.yml").read_text())["nav"]
    assert {"Command-line client": "cli.md"} in navigation
    assert "](cli.md)" in (ROOT / "docs" / "index.md").read_text()
    assert "](cli.md)" in (ROOT / "docs" / "authentication.md").read_text()
    assert "docs/cli.md" in (ROOT / "README.md").read_text()


def test_the_docs_say_roles_are_not_access_controls() -> None:
    assert "Roles are labels on your identity, not access controls on simulations." in CLI_DOC
    assert "does not make your simulations private" in CLI_DOC
