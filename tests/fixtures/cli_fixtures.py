"""An isolated home for the CLI, and a guard that it stays off the network and out of the browser.

The CLI reads `COMPOSE_API_CLI_*` variables and a config file in the platform's user config directory, so every
fixture here clears the first and points the second into `tmp_path`: a developer's real profile never leaks into a test.
"""

import os
import socket
import sys
import webbrowser
from collections.abc import Generator
from pathlib import Path
from typing import NoReturn

import pytest

from compose_api.cli.config import ENV_PREFIX, default_config_path


def write_cli_config(path: Path, text: str, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    return path


@pytest.fixture
def cli_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The config file the CLI will read by default, inside `tmp_path` and not yet created."""
    for name in list(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    path = default_config_path()
    if not path.is_relative_to(home):
        pytest.fail(f"platformdirs ignores HOME and XDG_CONFIG_HOME on {sys.platform}; isolate the CLI another way")
    return path


@pytest.fixture
def cli_subprocess_env(cli_config_path: Path) -> dict[str, str]:
    """The whole environment for a CLI child process: the private home and nothing else, so no server settings."""
    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT") if name in os.environ}
    env.update(HOME=os.environ["HOME"], XDG_CONFIG_HOME=os.environ["XDG_CONFIG_HOME"])
    return env


@pytest.fixture
def no_network_or_browser(monkeypatch: pytest.MonkeyPatch) -> Generator[list[str]]:
    """Fail the test if the CLI opens a browser, connects a socket or binds a listener."""
    attempts: list[str] = []

    def refuse(name: str) -> object:
        def refused(*_args: object, **_kwargs: object) -> NoReturn:
            attempts.append(name)
            raise AssertionError(f"the CLI called {name}")

        return refused

    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, name, refuse(f"webbrowser.{name}"))
    for name in ("connect", "connect_ex", "bind"):
        monkeypatch.setattr(socket.socket, name, refuse(f"socket.{name}"))
    yield attempts
    assert attempts == [], f"the CLI reached for the network or a browser: {attempts}"
