"""The command tree, exit codes and `config show`; and, as a real program, the packaging and isolation contract."""

import json
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

import compose_api.cli.config
from compose_api.cli.config import BUILTIN_PROFILES, PROFILE_FIELDS
from compose_api.cli.errors import ExitCode
from compose_api.cli.main import build_parser, main
from compose_api.config import REPO_ROOT
from compose_api.version import __version__
from tests.fixtures.cli_fixtures import write_cli_config

CLIENT_ID = "AbCdEf0123456789AbCdEf0123456789"
# A profile the person defined themselves, without the client ID or connections the built-in profiles carry.
BARE_PROFILE = """
[profiles.dev]
api_base_url = "https://compose.example.org"
auth0_domain = "tenant.example.auth0.com"
auth0_audience = "https://api.compose.example.org"
"""
LEAK_CANARY = "server-secret-4c1d"

# Every command in the documented surface, with the options each one takes. The first three sign in; the rest use
# a session.
SIGN_IN_FLOW_COMMANDS = [
    ["auth", "signup"],
    ["auth", "signup", "--provider", "google", "--no-browser"],
    ["auth", "login", "--device"],
]
SESSION_COMMANDS = [
    ["auth", "status", "--verify"],
    ["simulators", "list"],
    ["simulators", "list", "--ephemeral-auth", "--device"],
    ["simulations", "status", "123"],
    ["simulations", "submit", "experiment.omex", "--interval-time", "2.5", "--batch", "--ephemeral-auth"],
]
SIGN_IN_COMMANDS = [*SIGN_IN_FLOW_COMMANDS, *SESSION_COMMANDS]
ALL_COMMANDS = [["config", "show"], *SIGN_IN_COMMANDS]

# Run inside a child process: reports which heavyweight or server modules a command imported, and whether the
# server's dotenv files were loaded into the environment.
PROBE = """
import json, os, sys
from compose_api.cli.main import main
code = main(sys.argv[1:])
watched = ("compose_api.config", "compose_api.api", "compose_api.dependencies", "compose_api.authentication",
           "httpx", "pydantic", "platformdirs")
report = {"code": code, "imported": [m for m in watched if m in sys.modules],
          "server_env_loaded": "POSTGRES_PASSWORD" in os.environ}
print("PROBE " + json.dumps(report), file=sys.stderr)
"""


def test_exit_codes_are_the_documented_contract() -> None:
    assert {code.name: code.value for code in ExitCode} == {
        "OK": 0,
        "FAILURE": 1,
        "USAGE": 2,
        "AUTH_REQUIRED": 3,
        "FORBIDDEN": 4,
        "NETWORK": 5,
        "CONFIG": 6,
        "CANCELLED": 130,
    }


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == ExitCode.OK
    assert capsys.readouterr().out == f"compose-api {__version__}\n"


@pytest.mark.parametrize("argv", ALL_COMMANDS)
def test_every_documented_command_is_registered(argv: list[str]) -> None:
    args = build_parser().parse_args(argv)
    assert callable(args.handler)


def test_provider_defaults() -> None:
    parser = build_parser()
    assert parser.parse_args(["auth", "signup"]).provider == "email", "signup defaults to hosted email sign-up"
    assert parser.parse_args(["auth", "login"]).provider is None, "login leaves the choice to the hosted page"


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["auth"],
        ["frobnicate"],
        ["auth", "login", "--provider", "github"],
        ["auth", "login", "--device", "--no-browser"],
        ["auth", "login", "--token", "abc"],
        ["auth", "signup", "--password", "abc"],
        ["auth", "status", "--header", "Authorization: x"],
        ["simulations", "status"],
        ["simulations", "status", "abc"],
        ["simulations", "status", "0"],
        ["simulations", "status", "-3"],
        ["simulations", "submit"],
        ["simulations", "submit", "x.omex", "--interval-time", "nan"],
        ["simulations", "submit", "x.omex", "--interval-time", "inf"],
        ["simulations", "submit", "x.omex", "--interval-time", "0"],
        ["simulations", "submit", "x.omex", "--interval-time", "-1"],
        ["simulators", "list", "--device"],  # interactive sign-in is never implied
        ["simulators", "list", "--no-browser"],
        ["simulators", "list", "--ephemeral-auth", "--device", "--no-browser"],
    ],
)
def test_usage_errors_exit_2_without_output(
    capsys: pytest.CaptureFixture[str], no_network_or_browser: list[str], argv: list[str]
) -> None:
    assert main(argv) == ExitCode.USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage: compose-api" in captured.err


@pytest.mark.parametrize(
    "argv",
    [
        ["--json", "--profile", "local", "config", "show"],
        ["config", "--json", "show", "--profile", "local"],
        ["--profile", "local", "config", "show", "--json"],
        ["config", "show", "--json", "--profile", "local"],
    ],
)
def test_global_options_work_before_or_after_the_command(
    capsys: pytest.CaptureFixture[str], cli_config_path: Path, argv: list[str]
) -> None:
    assert main(argv) == ExitCode.OK
    view = json.loads(capsys.readouterr().out)
    assert view["profile"] == {"value": "local", "source": "--profile"}


def test_config_show_text(capsys: pytest.CaptureFixture[str], cli_config_path: Path) -> None:
    assert main(["config", "show"]) == ExitCode.OK
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert lines[0].split() == ["profile", "production", "(default)"]
    assert lines[1].startswith("config file") and lines[1].endswith(f"{cli_config_path}  (not found)")
    assert [line.split()[0] for line in lines[2:]] == [*PROFILE_FIELDS, "issuer", "redirect_uri"]
    assert lines[5].split() == ["auth0_client_id", BUILTIN_PROFILES["production"]["auth0_client_id"], "(default)"]
    assert captured.err == "", "the built-in profiles can sign in"


def test_config_show_notes_a_profile_that_cannot_sign_in(
    capsys: pytest.CaptureFixture[str], cli_config_path: Path
) -> None:
    write_cli_config(cli_config_path, BARE_PROFILE)
    assert main(["config", "show", "--profile", "dev"]) == ExitCode.OK
    assert "auth0_client_id is not set, so profile 'dev' cannot sign in yet" in capsys.readouterr().err


def test_config_show_reports_provenance_and_nothing_secret(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, cli_config_path: Path, tmp_path: Path
) -> None:
    secret_file = tmp_path / "secret.env"
    secret_file.write_text(f"POSTGRES_PASSWORD={LEAK_CANARY}\n")
    monkeypatch.setenv("SECRET_ENV_FILE", str(secret_file))
    monkeypatch.setenv("POSTGRES_PASSWORD", LEAK_CANARY)
    monkeypatch.setenv("SLURM_SUBMIT_KEY_PATH", LEAK_CANARY)
    monkeypatch.setenv("AUTH0_AUDIENCE", LEAK_CANARY)  # the server's variable, not the CLI's
    monkeypatch.setenv("COMPOSE_API_CLI_AUTH0_AUDIENCE", "https://api.compose.example.org")
    write_cli_config(cli_config_path, f'[profiles.production]\nauth0_client_id = "{CLIENT_ID}"\n')

    assert main(["config", "show", "--json"]) == ExitCode.OK
    captured = capsys.readouterr()
    view = json.loads(captured.out)
    assert view["config_file"] == {"path": str(cli_config_path), "found": True}
    assert set(view["settings"]) == set(PROFILE_FIELDS)
    assert view["settings"]["auth0_audience"] == {
        "value": "https://api.compose.example.org",
        "source": "env COMPOSE_API_CLI_AUTH0_AUDIENCE",
    }
    assert view["settings"]["auth0_client_id"]["source"] == "file [profiles.production]"
    assert view["settings"]["api_base_url"]["source"] == "default"
    assert LEAK_CANARY not in captured.out + captured.err
    assert captured.err == ""


@pytest.mark.parametrize("argv", ALL_COMMANDS)
def test_invalid_configuration_fails_before_network_or_browser(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    no_network_or_browser: list[str],
    argv: list[str],
) -> None:
    monkeypatch.setenv("COMPOSE_API_CLI_AUTH0_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("COMPOSE_API_CLI_API_BASE_URL", "http://compose.example.org")
    assert main(argv) == ExitCode.CONFIG
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "api_base_url (env COMPOSE_API_CLI_API_BASE_URL) must use https" in captured.err


@pytest.mark.parametrize("argv", SIGN_IN_COMMANDS)
def test_missing_public_client_id_fails_before_network_or_browser(
    capsys: pytest.CaptureFixture[str], cli_config_path: Path, no_network_or_browser: list[str], argv: list[str]
) -> None:
    write_cli_config(cli_config_path, BARE_PROFILE)
    assert main([*argv, "--profile", "dev"]) == ExitCode.CONFIG
    assert "set COMPOSE_API_CLI_AUTH0_CLIENT_ID" in capsys.readouterr().err


@pytest.mark.parametrize("argv", SIGN_IN_FLOW_COMMANDS)
def test_sign_in_stops_before_the_browser_while_there_is_nowhere_to_keep_a_session(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    no_network_or_browser: list[str],
    argv: list[str],
) -> None:
    monkeypatch.setenv("COMPOSE_API_CLI_AUTH0_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("COMPOSE_API_CLI_GOOGLE_CONNECTION", "google-oauth2")
    import keyring
    from keyring.backends.fail import Keyring

    monkeypatch.setattr(keyring, "get_keyring", Keyring)
    assert main([*argv, "--json"]) == ExitCode.CONFIG
    captured = capsys.readouterr()
    error = json.loads(captured.out)["error"]
    assert error["category"] == "storage"
    assert "Unsupported OS credential backend" in error["message"]


def test_google_sign_in_needs_its_connection_named(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    no_network_or_browser: list[str],
) -> None:
    write_cli_config(cli_config_path, BARE_PROFILE)
    monkeypatch.setenv("COMPOSE_API_CLI_AUTH0_CLIENT_ID", CLIENT_ID)
    assert main(["auth", "login", "--provider", "google", "--profile", "dev"]) == ExitCode.CONFIG
    assert "needs google_connection set for profile 'dev'" in capsys.readouterr().err
    # With --device the provider is chosen on the hosted page, so no connection is needed; the tests' refusing
    # credential store is what stops this one, still before any network request.
    assert main(["auth", "login", "--provider", "google", "--device", "--profile", "dev"]) == ExitCode.CONFIG
    assert "Unsupported OS credential backend" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [argv for argv in SESSION_COMMANDS if "--ephemeral-auth" not in argv])
def test_session_commands_need_a_usable_store_and_never_fall_back(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    no_network_or_browser: list[str],
    argv: list[str],
) -> None:
    """With no supported OS store (the tests' default) and no --ephemeral-auth, nothing is sent and nothing opens.

    The --ephemeral-auth variants need no store; tests/cli/test_api.py runs them end to end.
    """
    monkeypatch.setenv("COMPOSE_API_CLI_AUTH0_CLIENT_ID", CLIENT_ID)
    if argv[:2] == ["simulations", "submit"]:
        archive = cli_config_path.parent / "experiment.omex"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w") as contents:
            contents.writestr("manifest.xml", "<omexManifest/>")
        argv = [*argv[:2], str(archive), *argv[3:]]
    assert main([*argv, "--json"]) == ExitCode.CONFIG
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["category"] == "storage"
    assert "--ephemeral-auth" in error["message"], "a host without a store is pointed at the memory-only alternative"


def test_json_errors_are_objects_on_stdout(capsys: pytest.CaptureFixture[str], cli_config_path: Path) -> None:
    write_cli_config(cli_config_path, BARE_PROFILE)
    assert main(["auth", "login", "--json", "--profile", "dev"]) == ExitCode.CONFIG
    captured = capsys.readouterr()
    error = json.loads(captured.out)["error"]
    assert error["category"] == "configuration"
    assert "auth0_client_id is not set" in error["message"]
    assert captured.err.startswith("compose-api: error: ")


def test_ctrl_c_exits_130(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, cli_config_path: Path
) -> None:
    def interrupted(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(compose_api.cli.config, "load_cli_settings", interrupted)
    assert main(["config", "show"]) == ExitCode.CANCELLED
    assert capsys.readouterr().err == "compose-api: cancelled\n"


def test_entry_point_is_declared() -> None:
    project = tomllib.loads((Path(REPO_ROOT) / "pyproject.toml").read_text())["project"]
    assert project["scripts"] == {"compose-api": "compose_api.cli.main:main"}


def _run(command: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, timeout=60, check=False)  # noqa: S603


@pytest.mark.parametrize("argv", [["--help"], ["auth", "--help"], ["auth", "login", "--help"], ["--version"]])
def test_installed_entry_point_and_module_are_the_same_program(
    cli_subprocess_env: dict[str, str], tmp_path: Path, argv: list[str]
) -> None:
    entry_point = shutil.which("compose-api", path=str(Path(sys.executable).parent))
    if entry_point is None:
        pytest.fail("the compose-api entry point is not installed in this environment: run `uv sync`")
    installed = _run([entry_point, *argv], cli_subprocess_env, tmp_path)
    module = _run([sys.executable, "-m", "compose_api.cli", *argv], cli_subprocess_env, tmp_path)
    assert installed.returncode == module.returncode == 0, installed.stderr + module.stderr
    assert installed.stdout == module.stdout
    assert installed.stdout.startswith(f"compose-api {__version__}" if argv == ["--version"] else "usage: compose-api")


@pytest.mark.parametrize(
    ("argv", "allowed"),
    [
        (["--help"], []),
        (["--version"], []),
        (["auth", "login", "--help"], []),
        (["config", "show"], ["pydantic", "platformdirs"]),
    ],
)
def test_runs_without_server_settings_or_imports(
    cli_subprocess_env: dict[str, str], tmp_path: Path, argv: list[str], allowed: list[str]
) -> None:
    server_env = tmp_path / "server.env"
    server_env.write_text(f"POSTGRES_PASSWORD={LEAK_CANARY}\n")
    env = {**cli_subprocess_env, "SECRET_ENV_FILE": str(server_env), "CONFIG_ENV_FILE": str(server_env)}
    # A config file in the working directory is a decoy: only the user config directory is read.
    write_cli_config(tmp_path / "config.toml", '[profiles.production]\napi_base_url = "http://evil.example"\n')

    result = _run([sys.executable, "-c", PROBE, *argv], env, tmp_path)
    *_, probe_line = result.stderr.splitlines()
    report = json.loads(probe_line.removeprefix("PROBE "))
    assert report == {"code": 0, "imported": allowed, "server_env_loaded": False}, result.stderr
    assert LEAK_CANARY not in result.stdout + result.stderr
    assert "evil.example" not in result.stdout


def test_local_status_and_logout_json(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_network_or_browser: list[str],
) -> None:
    from compose_api.cli.auth import storage

    store = storage.MemoryCredentialStore()
    monkeypatch.setenv("COMPOSE_API_CLI_AUTH0_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(storage, "open_persistent_store", lambda *args, **kwargs: store)
    assert main(["auth", "status", "--json"]) == ExitCode.AUTH_REQUIRED
    status = json.loads(capsys.readouterr().out)
    assert (status["state"], status["checked_with_api"]) == ("missing", False)
    assert main(["auth", "logout", "--local-only", "--json"]) == ExitCode.OK
    assert json.loads(capsys.readouterr().out) == {"local_cleared": True, "revocation": "not_attempted"}
    assert next(iter(store.states.values())).read().generation == 1
