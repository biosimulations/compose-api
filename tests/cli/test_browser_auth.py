"""Browser sign-in: the loopback callback, the PKCE exchange, hosted sign-up hints, and what a failure leaves behind."""

import argparse
import asyncio
import logging
import socket
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from compose_api_client.auth.browser import auto_method, browser_sign_in, open_system_browser
from compose_api_client.auth.callback import CONNECTION_TIMEOUT_SECONDS, CallbackListener, CallbackResult
from compose_api_client.auth.models import Provider, SessionRecord, SignInMethod, SignInRequest
from compose_api_client.auth.oauth import Auth0OAuthClient
from compose_api_client.auth.signin import persistent_sign_in, resolve, sign_in
from compose_api_client.auth.storage import MemoryCredentialStore
from compose_api_client.cli.auth_commands import sign_in_command
from compose_api_client.cli.wiring import Wiring
from compose_api_client.ext.errors import AuthError, ConfigError, ExitCode, InteractionError
from compose_api_client.profiles import CliSettings

from tests.fixtures.auth_fixtures import AUTH0_TEST_AUDIENCE, AUTH0_TEST_DOMAIN, AUTH0_TEST_ISSUER
from tests.fixtures.cli_fixtures import (
    CLI_CLIENT_ID,
    CODE_PREFIX,
    DATABASE_CONNECTION,
    DESCRIPTION_CANARY,
    GOOGLE_CONNECTION,
    REFRESH_TOKEN,
    FakeBrowser,
    FakeComposeApi,
    FakeTenant,
    cli_settings,
    free_port,
    write_cli_config,
)

STATE = "expected-state-0123456789"


def _request(*, signup: bool = False, provider: Provider | None = None, open_browser: bool = True) -> SignInRequest:
    method = SignInMethod.BROWSER if open_browser else SignInMethod.URL
    return SignInRequest(signup=signup, provider=provider, method=method, persistent=True)


def _previous_session(settings: CliSettings) -> tuple[MemoryCredentialStore, SessionRecord]:
    """A store already holding someone's session, to show what a failed sign-in leaves alone."""
    store = MemoryCredentialStore()
    key = settings.binding_key(persistent=True)
    record = SessionRecord.model_validate({
        "binding_key": key,
        "identity": {"issuer": AUTH0_TEST_ISSUER, "subject": "auth0|previous"},
        "access_token": "previous-access",
        "access_token_expires_at": "2030-01-01T00:00:00Z",
        "refresh_token": "previous-refresh",
        "scopes": ["openid"],
        "obtained_at": "2029-12-31T00:00:00Z",
    })
    store.save(key, record)
    return store, record


@contextmanager
def _occupied(port: int) -> Iterator[None]:
    with socket.socket() as squatter:
        squatter.bind(("127.0.0.1", port))
        squatter.listen()
        yield


def _port_is_free(port: int) -> bool:
    """Nothing listens there any more. (A bind probe would be fooled by the closed connections' TIME_WAIT.)"""
    with socket.socket() as probe:
        probe.settimeout(2)
        return probe.connect_ex(("127.0.0.1", port)) != 0


async def _send(port: int, raw: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(raw)
    await writer.drain()
    response = await reader.read()
    writer.close()
    return response


def _get(port: int, target: str, *, host: str | None = None, extra: str = "") -> bytes:
    return f"GET {target} HTTP/1.1\r\nHost: {host or f'127.0.0.1:{port}'}\r\n{extra}\r\n".encode()


@pytest.mark.asyncio
async def test_the_listener_refuses_everything_but_the_real_callback() -> None:
    port = free_port()
    host = f"127.0.0.1:{port}"
    refused = [
        (_get(port, f"/callback?state=wrong&code={CODE_PREFIX}x"), 400),
        (_get(port, f"/callback?code={CODE_PREFIX}x"), 400),
        (_get(port, f"/callback?state={STATE}&state={STATE}&code={CODE_PREFIX}x"), 400),
        (_get(port, f"/callback?state={STATE}&code={CODE_PREFIX}x&code={CODE_PREFIX}y"), 400),
        (_get(port, f"/callback?state={STATE}"), 400),
        (_get(port, f"/callback?state={STATE}&code={CODE_PREFIX}x&error=access_denied"), 400),
        (_get(port, f"/callback?state={STATE}&code={CODE_PREFIX}x&iss=https://evil.example/"), 400),
        (_get(port, f"/callback?state={STATE}&code={CODE_PREFIX}x#fragment"), 400),
        (_get(port, f"/elsewhere?state={STATE}&code={CODE_PREFIX}x"), 404),
        (_get(port, f"/callback?state={STATE}&code={CODE_PREFIX}x", host=f"localhost:{port}"), 400),
        (_get(port, f"/callback?state={STATE}&code={CODE_PREFIX}x", host="evil.example"), 400),
        (_get(port, f"/callback?state={STATE}&code={CODE_PREFIX}x", extra=f"Host: {host}\r\n"), 400),
        (f"GET /callback?state={STATE}&code={CODE_PREFIX}x HTTP/1.1\r\n\r\n".encode(), 400),
        (f"POST /callback?state={STATE}&code={CODE_PREFIX}x HTTP/1.1\r\nHost: {host}\r\n\r\n".encode(), 405),
        (f"GET /callback?state={STATE}&code={CODE_PREFIX}x HTTP/2.0\r\nHost: {host}\r\n\r\n".encode(), 400),
        (_get(port, f"/callback?state={STATE}&code={CODE_PREFIX}x", extra=" folded: header\r\n"), 400),
        (f"GET /callback?state={STATE}&code=\xe9 HTTP/1.1\r\nHost: {host}\r\n\r\n".encode("latin-1"), 400),
        (_get(port, "/callback?" + "a=1&" * 20 + f"state={STATE}&code={CODE_PREFIX}x"), 400),
        (_get(port, f"/callback?state={STATE}&code={CODE_PREFIX}x", extra="X-Pad: " + "a" * 9000 + "\r\n"), 431),
    ]
    async with CallbackListener(port, state=STATE, issuer=AUTH0_TEST_ISSUER) as listener:
        for raw, status in refused:
            response = await _send(port, raw)
            assert response.startswith(f"HTTP/1.1 {status} ".encode()), (raw[:80], response[:40])
            assert CODE_PREFIX.encode() not in response and STATE.encode() not in response, "nothing is reflected"

        # None of that consumed the transaction: the real redirect still completes it.
        response = await _send(
            port, _get(port, f"/callback?state={STATE}&code={CODE_PREFIX}real&iss={AUTH0_TEST_ISSUER}")
        )
        assert await listener.wait(1) == CallbackResult(code=f"{CODE_PREFIX}real")

    head, _, body = response.partition(b"\r\n\r\n")
    headers = head.decode().lower()
    assert headers.startswith("http/1.1 200 ok")
    for header in (
        "cache-control: no-store",
        "content-security-policy: default-src 'none'",
        "referrer-policy: no-referrer",
        "x-content-type-options: nosniff",
    ):
        assert header in headers
    assert b"Signed in" in body and CODE_PREFIX.encode() not in body and STATE.encode() not in body
    assert _port_is_free(port), "the listener closes once it has its answer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"), [("access_denied", "access_denied"), ("Weird\x1bError", "unrecognised_error")]
)
async def test_an_error_redirect_ends_the_wait_without_its_description(error: str, expected: str) -> None:
    port = free_port()
    async with CallbackListener(port, state=STATE, issuer=AUTH0_TEST_ISSUER) as listener:
        query = httpx.QueryParams({"state": STATE, "error": error, "error_description": DESCRIPTION_CANARY})
        response = await _send(port, _get(port, f"/callback?{query}"))
        assert await listener.wait(1) == CallbackResult(error=expected)
    assert b"did not complete" in response and DESCRIPTION_CANARY.encode() not in response


@pytest.mark.asyncio
async def test_the_wait_is_bounded() -> None:
    async with CallbackListener(free_port(), state=STATE, issuer=AUTH0_TEST_ISSUER) as listener:
        with pytest.raises(AuthError, match="did not finish"):
            await listener.wait(0.05)


@pytest.mark.asyncio
async def test_closing_drops_a_connection_that_never_sends_a_request() -> None:
    # Without this, the listener would outlive the sign-in until that connection timed out: 3.12+'s `wait_closed`
    # waits for open connections, and `Server.close_clients()`, which drops them, is 3.13+ (the client is 3.11+).
    port = free_port()
    async with CallbackListener(port, state=STATE, issuer=AUTH0_TEST_ISSUER) as listener:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        async with asyncio.timeout(2):
            while not listener._connections:
                await asyncio.sleep(0.01)
        started = asyncio.get_running_loop().time()
        await listener.close()
        assert asyncio.get_running_loop().time() - started < CONNECTION_TIMEOUT_SECONDS / 4
        async with asyncio.timeout(2):
            assert await reader.read() == b"", "dropped without an answer"
        await listener._handle(reader, writer)
        assert listener._connections == set()
        writer.close()
    assert _port_is_free(port)


@pytest.mark.asyncio
async def test_browser_sign_in_end_to_end(fake_tenant: FakeTenant) -> None:
    settings = cli_settings()
    store = MemoryCredentialStore()
    browser = FakeBrowser(fake_tenant)
    messages: list[str] = []
    record = await persistent_sign_in(
        settings, _request(), store, notify=messages.append, launcher=browser, transport=fake_tenant.transport
    )

    assert record.identity.subject == fake_tenant.subject
    assert record.refresh_token is not None and record.refresh_token.get_secret_value() == REFRESH_TOKEN
    assert store.load(settings.binding_key(persistent=True)) == record
    [authorize] = fake_tenant.authorize_requests
    assert authorize["redirect_uri"] == f"http://127.0.0.1:{settings.callback_port}/callback"
    [callback] = browser.responses
    assert callback.status_code == 200 and "Signed in" in callback.text
    assert messages == ["Continue in the browser window that just opened. Waiting up to 5 minutes."]
    assert _port_is_free(settings.callback_port)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("signup", "provider", "database_connection", "expected"),
    [
        (True, None, DATABASE_CONNECTION, {"screen_hint": "signup", "prompt": "login"}),
        (
            True,
            Provider.EMAIL,
            DATABASE_CONNECTION,
            {"screen_hint": "signup", "prompt": "login", "connection": DATABASE_CONNECTION},
        ),
        (True, Provider.EMAIL, None, {"screen_hint": "signup", "prompt": "login"}),
        (True, Provider.GOOGLE, DATABASE_CONNECTION, {"prompt": "login", "connection": GOOGLE_CONNECTION}),
        (False, None, DATABASE_CONNECTION, {}),
        (False, Provider.EMAIL, DATABASE_CONNECTION, {"connection": DATABASE_CONNECTION}),
        (False, Provider.GOOGLE, DATABASE_CONNECTION, {"connection": GOOGLE_CONNECTION}),
    ],
)
async def test_sign_up_and_provider_hints(
    fake_tenant: FakeTenant,
    signup: bool,
    provider: Provider | None,
    database_connection: str | None,
    expected: dict[str, str],
) -> None:
    settings = cli_settings(database_connection=database_connection)
    await sign_in(
        settings,
        _request(signup=signup, provider=provider),
        notify=lambda _message: None,
        launcher=FakeBrowser(fake_tenant),
        transport=fake_tenant.transport,
    )
    [authorize] = fake_tenant.authorize_requests
    hints = {name: authorize[name] for name in ("screen_hint", "prompt", "connection") if name in authorize}
    assert hints == expected


@pytest.mark.asyncio
async def test_google_without_a_configured_connection_fails_before_anything(
    fake_tenant: FakeTenant, no_network_or_browser: list[str]
) -> None:
    browser = FakeBrowser(fake_tenant)
    with pytest.raises(ConfigError, match="google_connection"):
        await sign_in(
            cli_settings(google_connection=None, callback_port=8400),
            _request(provider=Provider.GOOGLE),
            notify=lambda _message: None,
            launcher=browser,
            transport=fake_tenant.transport,
        )
    assert browser.urls == [] and fake_tenant.requests == []


SSH = "192.0.2.10 51000 192.0.2.1 22"
VSCODE_HELPER = "/home/someone/.vscode-server/bin/0123abcd/bin/helpers/browser.sh"
VSCODE_IPC = "/run/user/1000/vscode-ipc-0123.sock"
PORT = 8411  # not the default, so a note that names the callback port is seen to take it from the profile


@pytest.mark.parametrize(
    ("platform", "env", "expected", "says"),
    [
        ("linux", {"DISPLAY": ":0"}, SignInMethod.BROWSER, ()),
        ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, SignInMethod.BROWSER, ()),
        ("darwin", {}, SignInMethod.BROWSER, ()),  # a desktop Mac always has a display, and no variable for it
        ("win32", {}, SignInMethod.BROWSER, ()),  # so does a Windows desktop
        ("linux", {"DISPLAY": ":0", "BROWSER": "firefox"}, SignInMethod.BROWSER, ()),  # a desktop's own choice
        ("linux", {}, SignInMethod.DEVICE, ("since this host has no display", f"port {PORT}", "--method url")),
        ("linux", {"BROWSER": "lynx"}, SignInMethod.DEVICE, ("since this host has no display",)),
        (
            "darwin",
            {"SSH_CONNECTION": SSH},
            SignInMethod.DEVICE,
            ("since this is an SSH session", f"ssh -L {PORT}:127.0.0.1:{PORT}", "--method url"),
        ),
        ("win32", {"SSH_CONNECTION": SSH}, SignInMethod.DEVICE, ("since this is an SSH session",)),
        # X11 forwarding: a browser would open, but on this host, and the callback could not reach it from there.
        ("linux", {"SSH_CONNECTION": SSH, "DISPLAY": "localhost:10.0"}, SignInMethod.DEVICE, ("an SSH session",)),
        # A text browser from a server's dotfiles would take over the terminal, and forwards nothing.
        ("linux", {"SSH_CONNECTION": SSH, "BROWSER": "w3m"}, SignInMethod.DEVICE, ("an SSH session",)),
        # VS Code without a $BROWSER helper has nothing to hand the link to.
        ("linux", {"SSH_CONNECTION": SSH, "VSCODE_IPC_HOOK_CLI": VSCODE_IPC}, SignInMethod.DEVICE, ("an SSH session",)),
        (
            "linux",
            {"SSH_CONNECTION": SSH, "BROWSER": VSCODE_HELPER, "VSCODE_IPC_HOOK_CLI": VSCODE_IPC},
            SignInMethod.BROWSER,
            ("through $BROWSER, since VS Code forwards the callback port", "--method device"),
        ),
        (
            "linux",
            {"SSH_CONNECTION": SSH, "BROWSER": VSCODE_HELPER, "TERM_PROGRAM": "vscode"},
            SignInMethod.BROWSER,
            ("since VS Code forwards the callback port",),
        ),
        (  # a Dev Container: no SSH and no display, and VS Code forwards its ports too
            "linux",
            {"BROWSER": VSCODE_HELPER, "TERM_PROGRAM": "vscode"},
            SignInMethod.BROWSER,
            ("since VS Code forwards the callback port",),
        ),
        (  # WSL without WSLg: no display, and wslview opens the Windows browser
            "linux",
            {"BROWSER": "wslview", "WSL_DISTRO_NAME": "Ubuntu"},
            SignInMethod.BROWSER,
            ("since WSL forwards the callback port", "--method device"),
        ),
    ],
    ids=[
        "linux-x11",
        "linux-wayland",
        "macos-desktop",
        "windows-desktop",
        "desktop-browser-env",
        "headless",
        "headless-text-browser",
        "ssh-macos",
        "ssh-windows",
        "ssh-x11-forwarding",
        "ssh-text-browser",
        "ssh-vscode-without-browser-env",
        "vscode-remote-ssh",
        "vscode-remote-ssh-term-program",
        "vscode-dev-container",
        "wsl",
    ],
)
def test_auto_picks_from_the_environment_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    env: dict[str, str],
    expected: SignInMethod,
    says: tuple[str, ...],
) -> None:
    _environment(monkeypatch, **env)
    monkeypatch.setattr("sys.platform", platform)
    method, note = auto_method(PORT)
    assert method is expected
    if not says:
        assert note is None, "the browser on this computer's desktop goes without saying"
        return
    assert note is not None
    flat = " ".join(note.split())
    assert all(fragment in flat for fragment in says), flat
    # Over SSH it would open on this host's screen, and without a display it cannot open at all.
    assert "--method browser" not in flat


def test_auto_picks_device_in_a_codespace_even_with_vscode_and_browser_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # A codespace opened in a web browser cannot receive the callback on 127.0.0.1, whatever $BROWSER does with a link.
    _environment(monkeypatch, CODESPACES="true", BROWSER="/vscode/bin/helpers/browser.sh", TERM_PROGRAM="vscode")
    monkeypatch.setattr("sys.platform", "linux")
    method, note = auto_method(PORT)
    assert method is SignInMethod.DEVICE
    assert note is not None and "since this is a GitHub Codespace" in note
    assert "--method browser works too" in " ".join(note.split()), "it does, from desktop VS Code"


@pytest.mark.parametrize("method", [SignInMethod.BROWSER, SignInMethod.URL, SignInMethod.DEVICE])
def test_an_explicit_method_is_never_second_guessed(monkeypatch: pytest.MonkeyPatch, method: SignInMethod) -> None:
    _environment(monkeypatch, SSH_CONNECTION=SSH, CODESPACES="true")
    notes: list[str] = []
    request = SignInRequest(signup=False, provider=None, method=method, persistent=True)
    assert resolve(cli_settings(), request, notify=notes.append) is request
    assert notes == []


@pytest.mark.parametrize(
    ("display", "browser_env", "platform", "handed_to"),
    [
        (":0", None, "linux", "default"),  # a Linux desktop
        (None, None, "darwin", "default"),  # macOS has no display variable and always a desktop
        (None, "/vscode/bin/helpers/browser.sh", "linux", "$BROWSER"),  # Remote-SSH: the helper opens it locally
        (None, None, "linux", None),  # headless with no handler: nothing to hand it to
    ],
)
def test_the_system_browser_is_the_desktop_or_browser_env(
    monkeypatch: pytest.MonkeyPatch,
    display: str | None,
    browser_env: str | None,
    platform: str,
    handed_to: str | None,
) -> None:
    _environment(monkeypatch, DISPLAY=display, BROWSER=browser_env)
    monkeypatch.setattr("sys.platform", platform)
    handed: list[tuple[str, str]] = []

    def default_open(url: str, new: int = 0, autoraise: bool = True) -> bool:
        handed.append(("default", url))  # webbrowser's whole list, text browsers included
        return True

    class FirstChoice:
        def open(self, url: str, new: int = 0, autoraise: bool = True) -> bool:
            handed.append(("$BROWSER", url))
            return True

    monkeypatch.setattr(webbrowser, "open", default_open)
    monkeypatch.setattr(webbrowser, "get", lambda using=None: FirstChoice())
    assert open_system_browser("https://tenant.example/authorize") is (handed_to is not None)
    assert handed == ([] if handed_to is None else [(handed_to, "https://tenant.example/authorize")])


@pytest.mark.parametrize("failure", ["no handler", "handler failed"])
def test_a_browser_env_that_does_not_open_is_not_a_browser(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    _environment(monkeypatch, BROWSER="/no/such/browser-helper")
    monkeypatch.setattr("sys.platform", "linux")

    class Fails:
        def open(self, url: str, new: int = 0, autoraise: bool = True) -> bool:
            return False  # GenericBrowser: the command exited non-zero, or could not start

    def get(using: str | None = None) -> Fails:
        if failure == "no handler":
            raise webbrowser.Error("could not locate runnable browser")
        return Fails()

    def default_open(url: str, new: int = 0, autoraise: bool = True) -> bool:
        raise AssertionError("without a display, webbrowser's other choices are text browsers")

    monkeypatch.setattr(webbrowser, "get", get)
    monkeypatch.setattr(webbrowser, "open", default_open)
    assert open_system_browser("https://tenant.example/authorize") is False


def _environment(monkeypatch: pytest.MonkeyPatch, **values: str | None) -> None:
    """Set the variables `auto` and the launcher read, clearing every one not given."""
    for name in (
        "SSH_CONNECTION",
        "BROWSER",
        "CODESPACES",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "VSCODE_IPC_HOOK_CLI",
        "TERM_PROGRAM",
        "WSL_DISTRO_NAME",
    ):
        value = values.get(name)
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


@pytest.mark.asyncio
async def test_the_url_method_prints_only_this_transactions_link(fake_tenant: FakeTenant) -> None:
    browser = FakeBrowser(fake_tenant)
    messages: list[str] = []

    def person_reads(message: str) -> None:
        messages.append(message)
        [link] = [line.strip() for line in message.splitlines() if line.strip().startswith("https://")]
        browser.visit_later(link)

    def never(_url: str) -> bool:
        raise AssertionError("--method url must not launch a browser")

    grant = await sign_in(
        cli_settings(),
        _request(open_browser=False),
        notify=person_reads,
        launcher=never,
        transport=fake_tenant.transport,
    )
    assert grant.identity.subject == fake_tenant.subject
    [message] = messages
    [link] = [line.strip() for line in message.splitlines() if line.strip().startswith("https://")]
    [authorize] = fake_tenant.authorize_requests
    assert dict(parse_qsl(urlsplit(link).query)) == authorize, "the printed link is this transaction's own"
    [form] = fake_tenant.forms(FakeTenant.TOKEN)
    assert form["code_verifier"] not in message and form["code"] not in message
    assert "--method device" in message


@pytest.mark.asyncio
async def test_a_browser_that_cannot_open_ends_cleanly(fake_tenant: FakeTenant) -> None:
    settings = cli_settings()
    with pytest.raises(InteractionError, match=r"--method url .* --method device"):
        await sign_in(
            settings,
            _request(),
            notify=lambda _m: None,
            launcher=FakeBrowser(fake_tenant, opens=False),
            transport=fake_tenant.transport,
        )
    assert fake_tenant.forms(FakeTenant.TOKEN) == []
    assert _port_is_free(settings.callback_port)


@pytest.mark.asyncio
async def test_an_occupied_callback_port_fails_before_the_browser_or_network(fake_tenant: FakeTenant) -> None:
    settings = cli_settings()
    browser = FakeBrowser(fake_tenant)
    with _occupied(settings.callback_port), pytest.raises(InteractionError, match="--method device"):
        await sign_in(settings, _request(), notify=lambda _m: None, launcher=browser, transport=fake_tenant.transport)
    assert browser.urls == [] and fake_tenant.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "queued", "error", "fragment"),
    [
        ("deny", None, AuthError, "cancelled or refused"),
        (
            "approve",
            httpx.Response(403, json={"error": "invalid_grant", "error_description": DESCRIPTION_CANARY}),
            AuthError,
            "invalid_grant",
        ),
    ],
)
async def test_a_failed_sign_in_keeps_the_previous_session(
    fake_tenant: FakeTenant, outcome: str, queued: httpx.Response | None, error: type[Exception], fragment: str
) -> None:
    settings = cli_settings()
    store, previous = _previous_session(settings)
    if queued is not None:
        fake_tenant.queue(FakeTenant.TOKEN, queued)
    with pytest.raises(error, match=fragment) as caught:
        await persistent_sign_in(
            settings,
            _request(),
            store,
            notify=lambda _m: None,
            launcher=FakeBrowser(fake_tenant, outcome=outcome),
            transport=fake_tenant.transport,
        )
    assert DESCRIPTION_CANARY not in str(caught.value)
    assert store.load(settings.binding_key(persistent=True)) == previous


@pytest.mark.asyncio
async def test_a_timed_out_sign_in_keeps_the_previous_session(fake_tenant: FakeTenant) -> None:
    settings = cli_settings()
    store, previous = _previous_session(settings)
    async with Auth0OAuthClient(settings, transport=fake_tenant.transport) as client:
        with pytest.raises(AuthError, match="did not finish"):
            await browser_sign_in(
                client,
                _request(),
                connection=None,
                launcher=FakeBrowser(fake_tenant, outcome="ignore"),
                notify=lambda _m: None,
                timeout=0.2,
            )
    assert store.load(settings.binding_key(persistent=True)) == previous
    assert fake_tenant.forms(FakeTenant.TOKEN) == []
    assert _port_is_free(settings.callback_port)


@pytest.mark.asyncio
async def test_a_cancelled_sign_in_keeps_the_previous_session_and_frees_the_port(fake_tenant: FakeTenant) -> None:
    settings = cli_settings()
    store, previous = _previous_session(settings)
    browser = FakeBrowser(fake_tenant, outcome="ignore")
    task = asyncio.create_task(
        persistent_sign_in(
            settings, _request(), store, notify=lambda _m: None, launcher=browser, transport=fake_tenant.transport
        )
    )
    while not browser.urls:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.load(settings.binding_key(persistent=True)) == previous
    assert _port_is_free(settings.callback_port)


@pytest.mark.asyncio
async def test_a_successful_sign_in_replaces_the_previous_session(fake_tenant: FakeTenant) -> None:
    settings = cli_settings()
    store, previous = _previous_session(settings)
    record = await persistent_sign_in(
        settings,
        _request(),
        store,
        notify=lambda _m: None,
        launcher=FakeBrowser(fake_tenant),
        transport=fake_tenant.transport,
    )
    assert store.load(settings.binding_key(persistent=True)) == record != previous


def test_the_login_command_keeps_secrets_out_of_every_output(
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: object,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    settings = cli_settings()
    for field in ("api_base_url", "auth0_domain", "auth0_audience", "auth0_client_id", "callback_port"):
        monkeypatch.setenv(f"COMPOSE_API_CLI_{field.upper()}", str(getattr(settings, field)))
    store = MemoryCredentialStore()
    args = _login_args()

    wiring = Wiring(
        store_factory=lambda _settings: store,
        launcher=FakeBrowser(fake_tenant),
        auth0_transport=fake_tenant.transport,
        api_transport=fake_compose_api.transport,
    )
    assert sign_in_command(args, signup=False, wiring=wiring) == ExitCode.OK

    record = store.load(settings.binding_key(persistent=True))
    assert record is not None and record.identity.subject == fake_tenant.subject
    captured = capsys.readouterr()
    assert f"Identity: {fake_tenant.subject} ({AUTH0_TEST_ISSUER})" in captured.out
    assert "Continue in the browser window" in captured.err, "progress goes to stderr, results to stdout"
    [form] = fake_tenant.forms(FakeTenant.TOKEN)
    secrets = [record.access_token.get_secret_value(), REFRESH_TOKEN, form["code"], form["code_verifier"]]
    for secret in secrets:
        assert secret not in captured.out + captured.err + caplog.text


def test_the_login_command_checks_everything_local_before_the_browser(
    fake_tenant: FakeTenant, monkeypatch: pytest.MonkeyPatch, cli_config_path: Path, no_network_or_browser: list[str]
) -> None:
    # A profile with a client ID but no Google connection: asking for Google must fail before anything else.
    write_cli_config(
        cli_config_path,
        f"""
[profiles.dev]
api_base_url = "https://api.compose.test"
auth0_domain = "{AUTH0_TEST_DOMAIN}"
auth0_audience = "{AUTH0_TEST_AUDIENCE}"
auth0_client_id = "{CLI_CLIENT_ID}"
""",
    )
    args = _login_args(provider="google")
    args.profile = "dev"
    opened: list[CliSettings] = []

    def store_factory(chosen: CliSettings) -> MemoryCredentialStore:
        opened.append(chosen)
        return MemoryCredentialStore()

    wiring = Wiring(store_factory=store_factory, auth0_transport=fake_tenant.transport)
    with pytest.raises(ConfigError, match="google_connection"):
        sign_in_command(args, signup=False, wiring=wiring)
    assert opened == [] and fake_tenant.requests == []


@pytest.mark.asyncio
async def test_save_failure_after_sign_in_revokes_the_new_refresh_token(fake_tenant: FakeTenant) -> None:
    from compose_api_client.ext.errors import StorageError

    settings = cli_settings()

    class _OversizeRefusingStore(MemoryCredentialStore):
        def save(self, binding_key: str, record: SessionRecord) -> None:
            raise StorageError("Windows Credential Manager atomic item limit exceeded; use --ephemeral-auth")

    store = _OversizeRefusingStore()
    with pytest.raises(StorageError, match="--ephemeral-auth"):
        await persistent_sign_in(
            settings,
            _request(),
            store,
            notify=lambda _: None,
            launcher=FakeBrowser(fake_tenant),
            transport=fake_tenant.transport,
        )
    assert store.load(settings.binding_key(persistent=True)) is None
    assert fake_tenant.forms(FakeTenant.REVOKE) == [
        {"token": REFRESH_TOKEN, "client_id": str(settings.auth0_client_id), "token_type_hint": "refresh_token"}
    ]


def _login_args(*, provider: str | None = None) -> argparse.Namespace:
    """What `compose-api auth login [--provider P]` hands `sign_in_command` (see `commands.auth_login`)."""
    return argparse.Namespace(profile=None, provider=provider, method="browser", json=False)
