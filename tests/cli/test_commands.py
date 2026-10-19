"""The command tree, exit codes and `config show`; and, as a real program, the packaging and isolation contract."""

import json
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import click
import compose_api_client.profiles
import pytest
import typer
from compose_api_client.auth.models import Provider, SignInMethod
from compose_api_client.cli.commands import METHODS, PROVIDERS, __version__, app, main
from compose_api_client.ext.errors import ExitCode
from compose_api_client.profiles import BUILTIN_PROFILES, PROFILE_FIELDS

from compose_api.config import REPO_ROOT
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

# Commands that sign in, use a session, or read the profile, with the options each one takes. Root options
# (--profile, --ephemeral-auth, --method, -o) come before the command. "experiment.omex" stands for a
# real archive (`_with_archive`).
SIGN_IN_FLOW_COMMANDS = [
    ["auth", "signup"],
    ["auth", "signup", "--provider", "google", "--method", "url"],
    ["auth", "login", "--method", "device"],
]
EPHEMERAL_COMMANDS = [
    ["--ephemeral-auth", "--method", "device", "simulators", "list"],
    ["--ephemeral-auth", "run", "experiment.omex", "--interval", "2.5", "--batch"],
]
# API commands use the profile's stored session when there is one, and call anonymously when there is none.
API_COMMANDS = [["simulators", "list"], ["status", "123"]]
SESSION_COMMANDS = [["auth", "status", "--verify"], *API_COMMANDS, *EPHEMERAL_COMMANDS]
SIGN_IN_COMMANDS = [*SIGN_IN_FLOW_COMMANDS, *SESSION_COMMANDS]
ALL_COMMANDS = [["config", "show"], *SIGN_IN_COMMANDS]
# What cannot work without a client ID: signing in, and checking a session with the API.
NEEDS_CLIENT_ID = [*SIGN_IN_FLOW_COMMANDS, ["auth", "status", "--verify"], *EPHEMERAL_COMMANDS]


def _with_archive(argv: list[str], directory: Path) -> list[str]:
    """`argv` with "experiment.omex" replaced by a real (minimal) OMEX archive in `directory`."""
    if "experiment.omex" not in argv:
        return argv
    archive = directory / "experiment.omex"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as contents:
        contents.writestr("manifest.xml", "<omexManifest/>")
    return [str(archive) if part == "experiment.omex" else part for part in argv]


#: Options whose value is a separate word, so `_command_path` can skip it.
_VALUE_OPTIONS = frozenset({
    "--url",
    "--profile",
    "--timeout",
    "--output",
    "-o",
    "--method",
    "--provider",
    "--interval",
})


def _command_path(argv: list[str]) -> list[str]:
    """The command words of `argv`, without the root options in front and the arguments after."""
    words: list[str] = []
    skip_value = False
    for part in argv:
        if skip_value:
            skip_value = False
            continue
        if part.startswith("-"):
            skip_value = part in _VALUE_OPTIONS
            continue
        words.append(part)
    group: click.Command = typer.main.get_group(app)
    path: list[str] = []
    for word in words:
        if not isinstance(group, click.Group) or word not in group.commands:
            break
        group = group.commands[word]
        path.append(word)
    return path


# Run inside a child process: reports which heavyweight or server modules a command imported, and whether the
# server's dotenv files were loaded into the environment.
PROBE = """
import json, os, sys
from compose_api_client.cli.commands import main
code = main(sys.argv[1:])
watched = ("compose_api", "compose_api.config", "compose_api.api", "compose_api.dependencies",
           "compose_api.authentication", "pydantic", "platformdirs", "keyring", "authlib", "jwt", "portalocker")
report = {"code": code, "imported": [m for m in watched if m in sys.modules],
          "server_env_loaded": "POSTGRES_PASSWORD" in os.environ}
print("PROBE " + json.dumps(report), file=sys.stderr)
"""

EXT_PROBE = """
import json, sys
import compose_api_client.ext
watched = ("compose_api", "pydantic", "keyring", "authlib", "jwt", "portalocker")
print("EXT_PROBE " + json.dumps([m for m in watched if m in sys.modules]), file=sys.stderr)
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
        "WAIT_TIMEOUT": 7,
        "CANCELLED": 130,
    }


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == ExitCode.OK
    assert capsys.readouterr().out == f"compose-api {__version__}\n"


@pytest.mark.parametrize("argv", ALL_COMMANDS)
def test_every_documented_command_is_registered(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    path = _command_path(argv)
    command: click.Command = typer.main.get_group(app)
    for word in path:
        assert isinstance(command, click.Group)
        command = command.commands[word]
    assert path and not isinstance(command, click.Group), argv
    assert main([*path, "--help"]) == ExitCode.OK
    assert f"Usage: compose-api {' '.join(path)}" in click.unstyle(capsys.readouterr().out)


def test_the_option_choices_are_the_enums() -> None:
    # Literal in commands.py, so building the CLI does not import the auth package.
    assert list(METHODS.choices) == [method.value for method in SignInMethod]
    assert list(PROVIDERS.choices) == [provider.value for provider in Provider]


def test_provider_defaults() -> None:
    auth = typer.main.get_group(app).commands["auth"]
    assert isinstance(auth, click.Group)

    def provider_default(name: str) -> object:
        return next(param.default for param in auth.commands[name].params if param.name == "provider")

    assert provider_default("signup") == "email", "signup defaults to hosted email sign-up"
    assert provider_default("login") is None, "login leaves the choice to the hosted page"


@pytest.mark.parametrize(
    "argv",
    [
        ["frobnicate"],
        ["auth", "login", "--provider", "github"],
        ["auth", "login", "--method", "carrier-pigeon"],
        ["auth", "login", "--token", "abc"],
        ["auth", "signup", "--password", "abc"],
        ["auth", "status", "--header", "Authorization: x"],
        ["status"],
        ["status", "abc"],
        ["status", "0"],
        ["status", "-3"],
        ["run"],
        ["run", "no-such-archive.omex"],
        ["simulators", "list", "--method", "device"],  # interactive sign-in is never implied
        ["--method", "device", "simulators", "list"],
        ["--method", "url", "simulators", "list"],
        ["--method", "auto", "simulators", "list"],  # given at all, it needs --ephemeral-auth
    ],
)
def test_usage_errors_exit_2_without_output(
    capsys: pytest.CaptureFixture[str], no_network_or_browser: list[str], argv: list[str]
) -> None:
    assert main(argv) == ExitCode.USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Usage: compose-api" in captured.err


@pytest.mark.parametrize(
    "argv",
    [
        ["auth", "login", "--token", "SECRET-SENTINEL"],
        ["auth", "signup", "--password", "SECRET-SENTINEL"],
        ["auth", "status", "--header", "Authorization: SECRET-SENTINEL"],
        ["--token", "SECRET-SENTINEL", "health"],
    ],
)
def test_a_refused_secret_option_never_echoes_its_value(
    capsys: pytest.CaptureFixture[str], no_network_or_browser: list[str], argv: list[str]
) -> None:
    assert main(argv) == ExitCode.USAGE
    captured = capsys.readouterr()
    assert "SECRET-SENTINEL" not in captured.out + captured.err


@pytest.mark.parametrize("method", ["device", "auto"])
def test_method_needs_ephemeral_auth(
    capsys: pytest.CaptureFixture[str], no_network_or_browser: list[str], method: str
) -> None:
    assert main(["--method", method, "simulators", "list"]) == ExitCode.USAGE
    message = "--method chooses how --ephemeral-auth signs in, so it needs --ephemeral-auth"
    assert message in " ".join(capsys.readouterr().err.split())


@pytest.mark.parametrize("argv", [[], ["auth"]])
def test_a_group_without_a_command_shows_its_help(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    assert main(argv) == ExitCode.USAGE
    assert f"Usage: compose-api {' '.join(argv)}".rstrip() in click.unstyle(capsys.readouterr().out)


@pytest.mark.parametrize("interval", ["nan", "inf", "0", "-1"])
def test_run_refuses_a_nonsense_interval(
    capsys: pytest.CaptureFixture[str], no_network_or_browser: list[str], tmp_path: Path, interval: str
) -> None:
    argv = _with_archive(["run", "experiment.omex", "--interval", interval], tmp_path)
    assert main(argv) == ExitCode.USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "must be a positive, finite number" in captured.err


@pytest.mark.parametrize(
    "argv",
    [
        ["--profile", "local", "config", "show", "--json"],
        ["--profile", "local", "-o", "json", "config", "show"],
        ["-o", "json", "--profile", "local", "config", "show"],
    ],
)
def test_global_options_go_before_the_command(
    capsys: pytest.CaptureFixture[str], cli_config_path: Path, argv: list[str]
) -> None:
    assert main(argv) == ExitCode.OK
    view = json.loads(capsys.readouterr().out)
    assert view["profile"] == {"value": "local", "source": "--profile"}


def test_a_global_option_after_the_command_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], cli_config_path: Path
) -> None:
    assert main(["config", "show", "--profile", "local"]) == ExitCode.USAGE
    assert "No such option: --profile" in capsys.readouterr().err


def test_config_show_text(capsys: pytest.CaptureFixture[str], cli_config_path: Path) -> None:
    # Output is "auto" (a table on a terminal, JSON when piped, as for every command); ask for the human form.
    assert main(["-o", "table", "config", "show"]) == ExitCode.OK
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
    assert main(["--profile", "dev", "config", "show"]) == ExitCode.OK
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
    assert main(_with_archive(argv, cli_config_path.parent)) == ExitCode.CONFIG
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "api_base_url (env COMPOSE_API_CLI_API_BASE_URL) must use https" in captured.err


@pytest.mark.parametrize("argv", NEEDS_CLIENT_ID)
def test_missing_public_client_id_fails_before_network_or_browser(
    capsys: pytest.CaptureFixture[str], cli_config_path: Path, no_network_or_browser: list[str], argv: list[str]
) -> None:
    """Signing in needs the profile's public client ID. API commands without --ephemeral-auth do not: a profile
    that cannot sign in calls anonymously (tests/cli/test_api.py)."""
    write_cli_config(cli_config_path, BARE_PROFILE)
    assert main(["--profile", "dev", *_with_archive(argv, cli_config_path.parent)]) == ExitCode.CONFIG
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
    assert main(["-o", "json", *argv]) == ExitCode.CONFIG
    captured = capsys.readouterr()
    error = json.loads(captured.out)["error"]
    assert error["category"] == "storage"
    assert "Unsupported OS credential backend" in error["message"]


@pytest.mark.parametrize("argv", SIGN_IN_FLOW_COMMANDS)
def test_windows_sign_in_stops_before_the_browser_while_a_session_cannot_fit(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    no_network_or_browser: list[str],
    argv: list[str],
) -> None:
    """A realistic session overflows a Credential Manager item (#320). Refusing at the save would come after a
    completed sign-in, so persistent sign-in stops first, without even probing the store."""
    monkeypatch.setenv("COMPOSE_API_CLI_AUTH0_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("COMPOSE_API_CLI_GOOGLE_CONNECTION", "google-oauth2")
    import keyring
    from keyring.backends.Windows import WinVaultKeyring

    touched: list[str] = []
    for method in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(WinVaultKeyring, method, lambda *args, name=method: touched.append(name))
    monkeypatch.setattr(keyring, "get_keyring", WinVaultKeyring)
    assert main(["-o", "json", *argv]) == ExitCode.CONFIG
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["category"] == "storage"
    assert "Windows Credential Manager cannot hold a saved session yet" in error["message"]
    assert "--ephemeral-auth" in error["message"]
    assert touched == []


def test_google_sign_in_needs_its_connection_named(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    no_network_or_browser: list[str],
) -> None:
    write_cli_config(cli_config_path, BARE_PROFILE)
    monkeypatch.setenv("COMPOSE_API_CLI_AUTH0_CLIENT_ID", CLIENT_ID)
    assert main(["--profile", "dev", "auth", "login", "--provider", "google", "--method", "browser"]) == ExitCode.CONFIG
    assert "needs google_connection set for profile 'dev'" in capsys.readouterr().err
    # With --method device the provider is chosen on the hosted page, so no connection is needed; the tests' refusing
    # credential store is what stops this one, still before any network request.
    assert main(["--profile", "dev", "auth", "login", "--provider", "google", "--method", "device"]) == ExitCode.CONFIG
    assert "Unsupported OS credential backend" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["auth", "status", "--verify"]])
def test_session_commands_need_a_usable_store_and_never_fall_back(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    no_network_or_browser: list[str],
    argv: list[str],
) -> None:
    """A command about a stored session needs a supported OS store (the tests' default has none): nothing is sent and
    nothing opens.

    API commands need none: with no supported store there is no session, so they call anonymously; a store that
    exists but cannot be read is an error, never an anonymous call. tests/cli/test_api.py runs both end to end, and
    the --ephemeral-auth variants, which need no store.
    """
    monkeypatch.setenv("COMPOSE_API_CLI_AUTH0_CLIENT_ID", CLIENT_ID)
    assert main(["-o", "json", *argv]) == ExitCode.CONFIG
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["category"] == "storage"
    assert "--ephemeral-auth" in error["message"], "a host without a store is pointed at the memory-only alternative"


def test_json_errors_are_objects_on_stdout(capsys: pytest.CaptureFixture[str], cli_config_path: Path) -> None:
    write_cli_config(cli_config_path, BARE_PROFILE)
    assert main(["-o", "json", "--profile", "dev", "auth", "login"]) == ExitCode.CONFIG
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

    monkeypatch.setattr(compose_api_client.profiles, "load_cli_settings", interrupted)
    assert main(["config", "show"]) == ExitCode.CANCELLED
    assert capsys.readouterr().err == "compose-api: cancelled\n"


def test_entry_point_is_declared() -> None:
    root_project = tomllib.loads((Path(REPO_ROOT) / "pyproject.toml").read_text())["project"]
    assert "scripts" not in root_project
    client_project = tomllib.loads((Path(REPO_ROOT) / "clients" / "python" / "pyproject.toml").read_text())["project"]
    assert client_project["scripts"] == {"compose-api": "compose_api_client.cli:main"}


def _run(command: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        command, env=env, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False
    )


@pytest.mark.parametrize("argv", [["--help"], ["auth", "--help"], ["auth", "login", "--help"], ["--version"]])
def test_installed_entry_point_and_module_are_the_same_program(
    cli_subprocess_env: dict[str, str], tmp_path: Path, argv: list[str]
) -> None:
    entry_point = shutil.which("compose-api", path=str(Path(sys.executable).parent))
    if entry_point is None:
        pytest.fail("the compose-api entry point is not installed in this environment: run `uv sync`")
    installed = _run([entry_point, *argv], cli_subprocess_env, tmp_path)
    module = _run([sys.executable, "-m", "compose_api_client.cli", *argv], cli_subprocess_env, tmp_path)
    assert installed.returncode == module.returncode == 0, installed.stderr + module.stderr
    assert installed.stdout == module.stdout
    if argv == ["--version"]:
        assert installed.stdout == f"compose-api {__version__}\n"
    else:
        assert "Usage: compose-api" in installed.stdout


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["health", "--help"],
        ["run", "--help"],
        ["datasets", "list", "--help"],
        ["sedml", "--help"],
        ["auth", "login", "--help"],
        ["config", "show"],
    ],
)
def test_the_installed_command_is_the_full_cli(
    cli_subprocess_env: dict[str, str], tmp_path: Path, argv: list[str]
) -> None:
    """The real entry point runs the whole command tree: the API commands and `auth` / `config` alike."""
    result = _run([sys.executable, "-m", "compose_api_client.cli", *argv], cli_subprocess_env, tmp_path)
    assert result.returncode == 0, result.stderr
    if argv == ["--help"]:
        for command in ("run", "status", "datasets", "sedml", "auth", "config"):
            assert f" {command} " in result.stdout, command


def test_the_real_entry_point_never_echoes_a_token(cli_subprocess_env: dict[str, str], tmp_path: Path) -> None:
    result = _run(
        [sys.executable, "-m", "compose_api_client.cli", "--token", "SECRET-SENTINEL", "health"],
        cli_subprocess_env,
        tmp_path,
    )
    assert result.returncode == ExitCode.USAGE
    assert "SECRET-SENTINEL" not in result.stdout + result.stderr
    assert "COMPOSE_API_TOKEN" in result.stderr, "the refusal names what to use instead"


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


def test_ext_import_leaves_auth_dependencies_unloaded(cli_subprocess_env: dict[str, str], tmp_path: Path) -> None:
    result = _run([sys.executable, "-c", EXT_PROBE], cli_subprocess_env, tmp_path)
    assert result.returncode == 0, result.stderr
    *_, probe_line = result.stderr.splitlines()
    assert json.loads(probe_line.removeprefix("EXT_PROBE ")) == []


def test_local_status_and_logout_json(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_network_or_browser: list[str],
) -> None:
    from compose_api_client.auth import storage

    store = storage.MemoryCredentialStore()
    monkeypatch.setenv("COMPOSE_API_CLI_AUTH0_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(storage, "open_persistent_store", lambda *args, **kwargs: store)
    assert main(["-o", "json", "auth", "status"]) == ExitCode.AUTH_REQUIRED
    status = json.loads(capsys.readouterr().out)
    assert (status["state"], status["checked_with_api"]) == ("missing", False)
    assert main(["-o", "json", "auth", "logout", "--local-only"]) == ExitCode.OK
    assert json.loads(capsys.readouterr().out) == {"local_cleared": True, "revocation": "not_attempted"}
    assert next(iter(store.states.values())).read().generation == 1
