"""Browser sign-in: the loopback callback, the PKCE exchange, hosted sign-up hints, and what a failure leaves behind."""

import argparse
import asyncio
import logging
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from compose_api.cli.auth.browser import browser_sign_in
from compose_api.cli.auth.callback import CallbackListener, CallbackResult
from compose_api.cli.auth.models import Provider, SessionRecord, SignInRequest
from compose_api.cli.auth.oauth import Auth0OAuthClient
from compose_api.cli.auth.signin import persistent_sign_in, sign_in
from compose_api.cli.auth.storage import MemoryCredentialStore
from compose_api.cli.commands.auth import sign_in_command
from compose_api.cli.commands.common import Wiring
from compose_api.cli.config import CliSettings
from compose_api.cli.errors import AuthError, ConfigError, ExitCode, InteractionError
from compose_api.cli.main import build_parser
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
    return SignInRequest(signup=signup, provider=provider, device=False, open_browser=open_browser, persistent=True)


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


@pytest.mark.asyncio
async def test_no_browser_prints_only_this_transactions_link(fake_tenant: FakeTenant) -> None:
    browser = FakeBrowser(fake_tenant)
    messages: list[str] = []

    def person_reads(message: str) -> None:
        messages.append(message)
        [link] = [line.strip() for line in message.splitlines() if line.strip().startswith("https://")]
        browser.visit_later(link)

    def never(_url: str) -> bool:
        raise AssertionError("--no-browser must not launch a browser")

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
    assert "--device" in message


@pytest.mark.asyncio
async def test_a_browser_that_cannot_open_ends_cleanly(fake_tenant: FakeTenant) -> None:
    settings = cli_settings()
    with pytest.raises(InteractionError, match=r"--no-browser .* --device"):
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
    with _occupied(settings.callback_port), pytest.raises(InteractionError, match="--device"):
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
    args = _namespace(["auth", "login"])

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
    args = _namespace(["auth", "login", "--provider", "google"])
    args.profile = "dev"
    opened: list[CliSettings] = []

    def store_factory(chosen: CliSettings) -> MemoryCredentialStore:
        opened.append(chosen)
        return MemoryCredentialStore()

    wiring = Wiring(store_factory=store_factory, auth0_transport=fake_tenant.transport)
    with pytest.raises(ConfigError, match="google_connection"):
        sign_in_command(args, signup=False, wiring=wiring)
    assert opened == [] and fake_tenant.requests == []


def _namespace(argv: list[str]) -> argparse.Namespace:
    args = build_parser().parse_args(argv)
    args.profile, args.json = None, False
    return args
