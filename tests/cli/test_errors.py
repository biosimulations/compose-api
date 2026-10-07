"""The error, status and output contract: every failure has one exit code, one category and a safe next step."""

import asyncio
import inspect
import io
import json
import logging
import socket
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

import compose_api.cli.config
from compose_api.cli import errors
from compose_api.cli.auth.storage import MemoryCredentialStore
from compose_api.cli.commands.common import Wiring
from compose_api.cli.errors import CliError, ExitCode
from compose_api.cli.main import main
from tests.fixtures.cli_fixtures import (
    DESCRIPTION_CANARY,
    FakeBrowser,
    FakeComposeApi,
    FakeTenant,
    RecordingTransport,
    cli_settings,
    seed_session,
    use_profile,
    wire,
)

# The documented contract (plan §6): scripts rely on these pairs.
CONTRACT: dict[type[CliError], tuple[ExitCode, str]] = {
    errors.UsageError: (ExitCode.USAGE, "usage"),
    errors.AuthError: (ExitCode.AUTH_REQUIRED, "authentication"),
    errors.ForbiddenError: (ExitCode.FORBIDDEN, "forbidden"),
    errors.NetworkError: (ExitCode.NETWORK, "network"),
    errors.RateLimitedError: (ExitCode.NETWORK, "rate_limited"),
    errors.ConfigError: (ExitCode.CONFIG, "configuration"),
    errors.StorageError: (ExitCode.CONFIG, "storage"),
    errors.ProtocolError: (ExitCode.CONFIG, "protocol"),
    errors.InteractionError: (ExitCode.CONFIG, "interaction"),
    errors.NotFoundError: (ExitCode.FAILURE, "not_found"),
    errors.InvalidRequestError: (ExitCode.FAILURE, "invalid_request"),
    errors.ServerError: (ExitCode.FAILURE, "server_error"),
    errors.ApiError: (ExitCode.FAILURE, "api_error"),
}


def _archive(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.xml", "<omexManifest/>")
    return path


def test_every_error_class_is_in_the_contract() -> None:
    defined = {
        cls
        for _, cls in inspect.getmembers(errors, inspect.isclass)
        if issubclass(cls, CliError) and cls is not CliError
    }
    assert defined == set(CONTRACT), "a new error class needs an exit code and category in the documented contract"


@pytest.mark.parametrize("error", list(CONTRACT), ids=lambda cls: cls.__name__)
def test_each_error_reports_one_line_and_one_json_object(
    error: type[CliError],
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, category = CONTRACT[error]

    def fail(*_args: object, **_kwargs: object) -> None:
        raise error("what went wrong; what to do next")

    monkeypatch.setattr(compose_api.cli.config, "load_cli_settings", fail)
    assert main(["config", "show", "--json"]) == code
    captured = capsys.readouterr()
    assert captured.err == "compose-api: error: what went wrong; what to do next\n"
    assert json.loads(captured.out) == {
        "error": {"category": category, "message": "what went wrong; what to do next", "exit_code": int(code)}
    }


def test_an_unexpected_failure_shows_its_type_only(
    monkeypatch: pytest.MonkeyPatch, cli_config_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def bug(*_args: object, **_kwargs: object) -> None:
        raise ValueError(f"something holding {DESCRIPTION_CANARY}")

    monkeypatch.setattr(compose_api.cli.config, "load_cli_settings", bug)
    assert main(["config", "show", "--json"]) == ExitCode.FAILURE
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"]["category"] == "internal"
    assert "internal error (ValueError)" in captured.err
    assert DESCRIPTION_CANARY not in captured.out + captured.err
    assert "Traceback" not in captured.err


def test_control_characters_never_reach_the_terminal(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def hostile(*_args: object, **_kwargs: object) -> None:
        raise errors.ProtocolError("a value with \x1b[2J a screen clear and \x07 a bell\nsecond line")

    with monkeypatch.context() as patched:
        patched.setattr(compose_api.cli.config, "load_cli_settings", hostile)
        main(["config", "show"])
    err = capsys.readouterr().err
    assert "\x1b" not in err and "\x07" not in err and "\\x1b[2J" in err
    assert "\nsecond line" in err, "the CLI's own line breaks survive"

    settings = cli_settings(callback_port=8400)
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    fake_tenant.subject = "auth0|\x1b]8;;https://evil.example\x07click\x1b]8;;\x07"
    asyncio.run(seed_session(settings, fake_tenant, store))
    wire(monkeypatch, Wiring(store_factory=lambda _settings: store))
    assert main(["auth", "status"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out and "evil.example" in out


@dataclass
class Scenario:
    """One row of the plan's §12 failure matrix, run through `main()` against the fakes."""

    argv: list[str]
    code: ExitCode
    category: str
    advice: str  # the safe next step the message must name
    api: Callable[[httpx.Request], httpx.Response] | None = None  # None: the real app over ASGI
    session: dict[str, object] | None = field(default_factory=dict)  # None: no stored session
    token_answers: list[httpx.Response] = field(default_factory=list)
    renews: bool = False  # Auth0 answers one renewal with a rotated refresh token
    auth0_down: bool = False  # Auth0's discovery fails, so a renewal never sends the refresh token
    browser: str = "approve"
    archive: bytes | None = None
    occupy_callback_port: bool = False
    keyring: bool = True


def _status(status: int, **headers: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(status, headers=headers, text=DESCRIPTION_CANARY)


def _unreachable(_request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused")


SCENARIOS: dict[str, Scenario] = {
    "no-session": Scenario(
        ["simulators", "list"], ExitCode.AUTH_REQUIRED, "authentication", "sign in first", session=None
    ),
    "refresh-revoked": Scenario(
        ["simulators", "list"],
        ExitCode.AUTH_REQUIRED,
        "authentication",
        "sign in again",
        session={"expires_in": 30},
        token_answers=[httpx.Response(403, json={"error": "invalid_grant", "error_description": DESCRIPTION_CANARY})],
    ),
    "auth0-unreachable-before-renewal": Scenario(
        ["simulators", "list"], ExitCode.NETWORK, "network", "try again", session={"expires_in": 30}, auth0_down=True
    ),
    "rejected-twice": Scenario(
        ["simulators", "list"],
        ExitCode.AUTH_REQUIRED,
        "authentication",
        "auth0_audience",
        api=_status(401),
        renews=True,
    ),
    "forbidden": Scenario(
        ["simulators", "list"], ExitCode.FORBIDDEN, "forbidden", "signing in again will not change", api=_status(403)
    ),
    "not-found": Scenario(["simulations", "status", "999"], ExitCode.FAILURE, "not_found", "no simulation 999"),
    "invalid": Scenario(
        ["simulations", "status", "5"], ExitCode.FAILURE, "invalid_request", "invalid", api=_status(422)
    ),
    "rate-limited": Scenario(
        ["simulators", "list"],
        ExitCode.NETWORK,
        "rate_limited",
        "retry after 30 s",
        api=_status(429, **{"Retry-After": "30"}),
    ),
    "api-unavailable": Scenario(
        ["simulators", "list"], ExitCode.NETWORK, "network", "try again later", api=_status(503)
    ),
    "api-unreachable": Scenario(
        ["simulators", "list"], ExitCode.NETWORK, "network", "check the connection", api=_unreachable
    ),
    "submission-outcome-unknown": Scenario(
        ["simulations", "submit", "{archive}"],
        ExitCode.FAILURE,
        "server_error",
        "do not submit again blindly",
        api=_status(500),
        archive=b"zip",
    ),
    "server-error": Scenario(["simulators", "list"], ExitCode.FAILURE, "server_error", "HTTP 500", api=_status(500)),
    "redirect": Scenario(
        ["simulators", "list"],
        ExitCode.CONFIG,
        "protocol",
        "Check api_base_url",
        api=_status(307, Location="https://evil.example/"),
    ),
    "not-an-archive": Scenario(
        ["simulations", "submit", "{archive}"], ExitCode.USAGE, "usage", "not an OMEX archive", archive=b"plain text"
    ),
    "no-credential-store": Scenario(
        ["simulators", "list"], ExitCode.CONFIG, "storage", "--ephemeral-auth", session=None, keyring=False
    ),
    "api-unreachable-after-login": Scenario(
        ["auth", "login"], ExitCode.NETWORK, "network", "auth status --verify", api=_unreachable, session=None
    ),
    "denied-in-browser": Scenario(
        ["auth", "login"], ExitCode.AUTH_REQUIRED, "authentication", "nothing was saved", session=None, browser="deny"
    ),
    "no-browser": Scenario(
        ["auth", "login"], ExitCode.CONFIG, "interaction", "--no-browser", session=None, browser="cannot-open"
    ),
    "callback-port-taken": Scenario(
        ["auth", "login"], ExitCode.CONFIG, "interaction", "--device", session=None, occupy_callback_port=True
    ),
}


@pytest.mark.parametrize("scenario", list(SCENARIOS.values()), ids=list(SCENARIOS))
def test_each_failure_in_the_matrix_has_its_code_and_a_safe_next_step(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    tmp_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = cli_settings()
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    if scenario.session is not None:
        asyncio.run(seed_session(settings, fake_tenant, store, **scenario.session))  # type: ignore[arg-type]
    fake_tenant.queue(FakeTenant.TOKEN, *scenario.token_answers)
    if scenario.renews:
        fake_tenant.queue(
            FakeTenant.TOKEN,
            fake_tenant.token_response(refresh_token="rt-rotated", include_id_token=False),  # noqa: S106 -- test data
        )
    if scenario.auth0_down:
        fake_tenant.handle = _discovery_down(fake_tenant)  # type: ignore[method-assign]
    api = fake_compose_api.transport if scenario.api is None else RecordingTransport(httpx.MockTransport(scenario.api))
    browser = FakeBrowser(fake_tenant, outcome=scenario.browser, opens=scenario.browser != "cannot-open")
    if scenario.keyring:
        wire(
            monkeypatch,
            Wiring(
                store_factory=lambda _settings: store,
                launcher=browser,
                auth0_transport=fake_tenant.transport,
                api_transport=api,
            ),
        )
    argv = list(scenario.argv)
    if scenario.archive is not None:
        archive = tmp_path / "experiment.omex"
        if scenario.archive == b"zip":
            _archive(archive)
        else:
            archive.write_bytes(scenario.archive)
        argv = [part.format(archive=archive) for part in argv]

    with socket.socket() as squatter:
        if scenario.occupy_callback_port:
            squatter.bind(("127.0.0.1", settings.callback_port))
            squatter.listen()
        code = main([*argv, "--json"])
    captured = capsys.readouterr()
    error = json.loads(captured.out.splitlines()[-1])["error"]
    assert (code, error["category"], error["exit_code"]) == (scenario.code, scenario.category, int(scenario.code))
    assert scenario.advice in error["message"]
    assert DESCRIPTION_CANARY not in captured.out + captured.err


def _discovery_down(tenant: FakeTenant) -> Callable[[httpx.Request], httpx.Response]:
    original = tenant.handle

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(503)
        return original(request)

    return handle


def test_a_refresh_that_never_left_keeps_the_session(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = cli_settings(callback_port=8400)
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    before = asyncio.run(seed_session(settings, fake_tenant, store, expires_in=30))
    fake_tenant.handle = _discovery_down(fake_tenant)  # type: ignore[method-assign]
    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: store,
            auth0_transport=fake_tenant.transport,
            api_transport=fake_compose_api.transport,
        ),
    )
    assert main(["simulators", "list"]) == ExitCode.NETWORK
    assert store.load(settings.binding_key(persistent=True)) == before
    assert fake_tenant.forms(FakeTenant.TOKEN) == []
    assert fake_compose_api.transport.requests == []


def test_a_whole_session_never_leaks_a_credential(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    tmp_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    settings = cli_settings()
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    fake_tenant.queue(FakeTenant.REVOKE, httpx.Response(200))
    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: store,
            launcher=FakeBrowser(fake_tenant),
            auth0_transport=fake_tenant.transport,
            api_transport=fake_compose_api.transport,
        ),
    )
    archive = _archive(tmp_path / "experiment.omex")
    journey = [
        ["auth", "login"],
        ["auth", "status", "--verify"],
        ["simulators", "list"],
        ["simulations", "submit", str(archive)],
        ["simulations", "status", str(FakeComposeApi.SIMULATION_ID)],
        ["auth", "status", "--json"],
    ]
    for argv in journey:
        assert main(argv) == ExitCode.OK, argv
    record = store.load(settings.binding_key(persistent=True))
    assert record is not None
    assert main(["auth", "logout"]) == ExitCode.OK

    secrets = {record.access_token.get_secret_value()}
    for body in fake_tenant.issued:
        secrets.update(str(body[name]) for name in ("access_token", "id_token", "refresh_token") if name in body)
    for form in fake_tenant.forms(FakeTenant.TOKEN):
        secrets.update(form[name] for name in ("code", "code_verifier", "refresh_token") if name in form)
    for request in fake_compose_api.transport.requests:
        secrets.add(request.headers["authorization"])
    captured = capsys.readouterr()
    shown = captured.out + captured.err + caplog.text
    assert len(secrets) >= 4
    for secret in secrets:
        assert secret not in shown
    assert "this computer only" in captured.err, "logout says what it did not end"


def test_text_and_json_report_the_same_facts(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = cli_settings(callback_port=8400)
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    asyncio.run(seed_session(settings, fake_tenant, store))
    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: store,
            auth0_transport=fake_tenant.transport,
            api_transport=fake_compose_api.transport,
        ),
    )
    for argv, facts in [
        (["auth", "status"], lambda d: [d["identity"]["subject"], d["identity"]["issuer"], d["state"]]),
        (["simulations", "status", "41"], lambda d: [str(d["sim_id"]), d["status"], str(d["slurmjobid"])]),
        (["simulators", "list"], lambda d: [str(v["database_id"]) for v in d["versions"]]),
    ]:
        assert main(argv) == ExitCode.OK
        text = capsys.readouterr().out
        assert main([*argv, "--json"]) == ExitCode.OK
        document = json.loads(capsys.readouterr().out)
        for fact in facts(document):
            assert str(fact) in text, (argv, fact)


def test_submitting_reads_the_archive_once_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    tmp_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
) -> None:
    settings = cli_settings(callback_port=8400)
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    asyncio.run(seed_session(settings, fake_tenant, store))
    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: store,
            auth0_transport=fake_tenant.transport,
            api_transport=fake_compose_api.transport,
        ),
    )
    opened: list[io.BufferedReader] = []
    original_open = Path.open

    def tracking_open(self: Path, *args: object, **kwargs: object) -> object:
        handle = original_open(self, *args, **kwargs)  # type: ignore[call-overload]
        if self.suffix == ".omex":
            opened.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", tracking_open)
    assert main(["simulations", "submit", str(_archive(tmp_path / "experiment.omex"))]) == ExitCode.OK
    assert len(opened) == 1 and opened[0].closed
