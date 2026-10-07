"""Device authorization (RFC 8628) and one-command ephemeral sessions."""

import asyncio
from typing import Any

import httpx
import pytest

from compose_api.cli.auth import signin
from compose_api.cli.auth.device import DEFAULT_INTERVAL_SECONDS, device_sign_in
from compose_api.cli.auth.models import Provider, SignInRequest, TokenGrant
from compose_api.cli.auth.oauth import DEVICE_CODE_GRANT, Auth0OAuthClient
from compose_api.cli.auth.signin import ephemeral_session, sign_in
from compose_api.cli.auth.storage import MemoryCredentialStore
from compose_api.cli.config import OFFLINE_ACCESS_SCOPE, CliSettings, requested_scopes
from compose_api.cli.errors import AuthError, ProtocolError
from tests.fixtures.auth_fixtures import AUTH0_TEST_AUDIENCE, AUTH0_TEST_ISSUER
from tests.fixtures.cli_fixtures import (
    CLI_CLIENT_ID,
    DESCRIPTION_CANARY,
    DEVICE_CODE,
    REFRESH_TOKEN,
    USER_CODE,
    FakeBrowser,
    FakeTenant,
    cli_settings,
)

PENDING = httpx.Response(400, json={"error": "authorization_pending"})
SLOW_DOWN = httpx.Response(400, json={"error": "slow_down"})


class FakeTime:
    """A monotonic clock that only moves when the poller sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _request(*, provider: Provider | None = None, persistent: bool = True) -> SignInRequest:
    return SignInRequest(signup=False, provider=provider, device=True, open_browser=False, persistent=persistent)


async def _device_sign_in(
    tenant: FakeTenant,
    clock: FakeTime,
    *,
    messages: list[str] | None = None,
    provider: Provider | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> TokenGrant:
    async with Auth0OAuthClient(cli_settings(), transport=transport or tenant.transport) as client:
        return await device_sign_in(
            client,
            _request(provider=provider),
            notify=(messages if messages is not None else []).append,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )


@pytest.mark.asyncio
async def test_polling_follows_the_interval_and_slows_down_when_asked(fake_tenant: FakeTenant) -> None:
    clock = FakeTime()
    messages: list[str] = []
    fake_tenant.queue(FakeTenant.DEVICE, fake_tenant.device_response())
    fake_tenant.queue(FakeTenant.TOKEN, PENDING, PENDING, SLOW_DOWN, PENDING, fake_tenant.token_response())

    grant = await _device_sign_in(fake_tenant, clock, messages=messages)

    assert grant.identity.subject == fake_tenant.subject
    assert grant.refresh_token is not None
    assert clock.sleeps == [5, 5, 5, 10, 10], "slow_down adds 5 s to this and every later poll"
    assert fake_tenant.forms(FakeTenant.DEVICE) == [
        {
            "client_id": CLI_CLIENT_ID,
            "scope": " ".join(requested_scopes(persistent=True)),
            "audience": AUTH0_TEST_AUDIENCE,
        }
    ]
    polls = fake_tenant.forms(FakeTenant.TOKEN)
    assert polls == [{"grant_type": DEVICE_CODE_GRANT, "device_code": DEVICE_CODE, "client_id": CLI_CLIENT_ID}] * 5
    [shown] = messages
    assert f"{AUTH0_TEST_ISSUER}activate" in shown and USER_CODE in shown
    assert f"activate?user_code={USER_CODE}" in shown
    assert "Only enter a code that you just printed yourself" in shown
    assert DEVICE_CODE not in shown


@pytest.mark.asyncio
async def test_the_default_interval_is_five_seconds(fake_tenant: FakeTenant) -> None:
    clock = FakeTime()
    fake_tenant.queue(FakeTenant.DEVICE, fake_tenant.device_response(interval=None))
    fake_tenant.queue(FakeTenant.TOKEN, PENDING, fake_tenant.token_response())
    await _device_sign_in(fake_tenant, clock)
    assert clock.sleeps == [DEFAULT_INTERVAL_SECONDS] * 2


@pytest.mark.asyncio
async def test_rate_limits_and_outages_back_off_within_the_deadline(fake_tenant: FakeTenant) -> None:
    clock = FakeTime()
    fake_tenant.queue(FakeTenant.DEVICE, fake_tenant.device_response())
    fake_tenant.queue(FakeTenant.TOKEN, httpx.Response(429), httpx.Response(503), fake_tenant.token_response())
    failures = iter([httpx.ConnectError("dropped")])

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path == FakeTenant.TOKEN and len(fake_tenant.forms(FakeTenant.TOKEN)) == 2:
            failure = next(failures, None)
            if failure is not None:
                raise failure
        return fake_tenant.handle(request)

    await _device_sign_in(fake_tenant, clock, transport=httpx.MockTransport(flaky))
    # 429 adds 5 (to 10); the 503 doubles (to 20); the dropped connection doubles again (to 40).
    assert clock.sleeps == [5, 10, 20, 40]


@pytest.mark.asyncio
async def test_polling_stops_at_the_deadline(fake_tenant: FakeTenant) -> None:
    clock = FakeTime()
    fake_tenant.queue(FakeTenant.DEVICE, fake_tenant.device_response(expires_in=12))
    fake_tenant.queue(FakeTenant.TOKEN, *[PENDING] * 10)
    with pytest.raises(AuthError, match="expired before sign-in finished"):
        await _device_sign_in(fake_tenant, clock)
    assert clock.sleeps == [5, 5, 2]
    assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 3
    assert len(fake_tenant.forms(FakeTenant.DEVICE)) == 1, "an expired code is never replaced automatically"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "error", "fragment"),
    [
        ({"error": "access_denied", "error_description": DESCRIPTION_CANARY}, AuthError, "refused on the other device"),
        ({"error": "expired_token"}, AuthError, "expired before sign-in finished"),
        ({"error": "invalid_client", "error_description": DESCRIPTION_CANARY}, ProtocolError, "invalid_client"),
        ({"error_description": DESCRIPTION_CANARY}, ProtocolError, "HTTP 400"),
    ],
)
async def test_final_device_errors_stop_polling(
    fake_tenant: FakeTenant, answer: dict[str, str], error: type[Exception], fragment: str
) -> None:
    fake_tenant.queue(FakeTenant.DEVICE, fake_tenant.device_response())
    fake_tenant.queue(FakeTenant.TOKEN, PENDING, httpx.Response(400, json=answer), fake_tenant.token_response())
    with pytest.raises(error, match=fragment) as caught:
        await _device_sign_in(fake_tenant, FakeTime())
    assert DESCRIPTION_CANARY not in str(caught.value)
    assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 2


NO_COMPLETE: dict[str, Any] = {"verification_uri_complete": None}
PAGE = "verification_uri is not an https page"
MALFORMED: list[tuple[str, dict[str, Any], str]] = [
    ("no-device-code", {"device_code": None}, "device_code"),
    ("blank-device-code", {"device_code": ""}, "device_code"),
    ("control-user-code", {"user_code": "WDJB\x1b[2J"}, "user_code"),
    ("spaced-user-code", {"user_code": "WDJB MJHT"}, "user_code"),
    ("http-page", {"verification_uri": "http://compose-test.example.auth0.com/activate", **NO_COMPLETE}, PAGE),
    ("foreign-page", {"verification_uri": "https://evil.example/activate", **NO_COMPLETE}, PAGE),
    (
        "lookalike-page",
        {"verification_uri": "https://compose-test.example.auth0.com.evil.example/a", **NO_COMPLETE},
        PAGE,
    ),
    ("userinfo-page", {"verification_uri": "https://x@compose-test.example.auth0.com/activate", **NO_COMPLETE}, PAGE),
    ("port-page", {"verification_uri": "https://compose-test.example.auth0.com:8443/activate", **NO_COMPLETE}, PAGE),
    ("fragment-page", {"verification_uri": "https://compose-test.example.auth0.com/activate#x", **NO_COMPLETE}, PAGE),
    ("no-page", {"verification_uri": None, **NO_COMPLETE}, "missing or malformed verification_uri$"),
    (
        "foreign-complete",
        {"verification_uri_complete": f"https://evil.example/activate?user_code={USER_CODE}"},
        "verification_uri_complete",
    ),
    (
        "other-code-complete",
        {"verification_uri_complete": f"{AUTH0_TEST_ISSUER}activate?user_code=AAAA-BBBB"},
        "verification_uri_complete",
    ),
    ("negative-expiry", {"expires_in": -1}, "expires_in"),
    ("zero-expiry", {"expires_in": 0}, "expires_in"),
    ("string-expiry", {"expires_in": "900"}, "expires_in"),
    ("bool-expiry", {"expires_in": True}, "expires_in"),
    ("no-expiry", {"expires_in": None}, "expires_in"),
    ("huge-expiry", {"expires_in": 10**6}, "expires_in"),
    ("zero-interval", {"interval": 0}, "interval"),
    ("negative-interval", {"interval": -5}, "interval"),
    ("string-interval", {"interval": "5"}, "interval"),
    ("bool-interval", {"interval": True}, "interval"),
    ("huge-interval", {"interval": 600}, "interval"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("changes", "fragment"), [(c, f) for _, c, f in MALFORMED], ids=[i for i, _, _ in MALFORMED])
async def test_a_malformed_device_answer_is_refused_before_anything_is_shown(
    fake_tenant: FakeTenant, changes: dict[str, Any], fragment: str
) -> None:
    body = {**fake_tenant.device_response(), **changes}
    fake_tenant.queue(FakeTenant.DEVICE, {name: value for name, value in body.items() if value is not None})
    messages: list[str] = []
    with pytest.raises(ProtocolError, match=fragment):
        await _device_sign_in(fake_tenant, FakeTime(), messages=messages)
    assert messages == [] and fake_tenant.forms(FakeTenant.TOKEN) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "fragment"),
    [
        (httpx.Response(403, json={"error": "unauthorized_client"}), "unauthorized_client"),
        (httpx.Response(200, json=["not", "an", "object"]), "malformed response"),
    ],
)
async def test_a_refused_device_request(fake_tenant: FakeTenant, answer: httpx.Response, fragment: str) -> None:
    fake_tenant.queue(FakeTenant.DEVICE, answer)
    with pytest.raises(ProtocolError, match=fragment):
        await _device_sign_in(fake_tenant, FakeTime())


@pytest.mark.asyncio
async def test_a_tenant_without_device_sign_in(fake_tenant: FakeTenant) -> None:
    fake_tenant.discovery.pop("device_authorization_endpoint")
    with pytest.raises(ProtocolError, match="does not offer device sign-in"):
        await _device_sign_in(fake_tenant, FakeTime())


@pytest.mark.asyncio
async def test_a_provider_with_device_is_advice_not_a_parameter(fake_tenant: FakeTenant) -> None:
    clock = FakeTime()
    messages: list[str] = []
    fake_tenant.queue(FakeTenant.DEVICE, fake_tenant.device_response())
    fake_tenant.queue(FakeTenant.TOKEN, fake_tenant.token_response())
    await _device_sign_in(fake_tenant, clock, messages=messages, provider=Provider.GOOGLE)
    assert "Choose Google on that page" in messages[0]
    assert "connection" not in fake_tenant.forms(FakeTenant.DEVICE)[0]


@pytest.mark.asyncio
async def test_device_sign_in_needs_no_google_connection(fake_tenant: FakeTenant) -> None:
    fake_tenant.queue(FakeTenant.DEVICE, fake_tenant.device_response(interval=1))
    fake_tenant.queue(FakeTenant.TOKEN, fake_tenant.token_response())
    grant = await sign_in(
        cli_settings(google_connection=None),
        _request(provider=Provider.GOOGLE),
        notify=lambda _m: None,
        transport=fake_tenant.transport,
    )
    assert grant.identity.subject == fake_tenant.subject


@pytest.mark.asyncio
async def test_cancelling_stops_polling(fake_tenant: FakeTenant) -> None:
    fake_tenant.queue(FakeTenant.DEVICE, fake_tenant.device_response())
    fake_tenant.queue(FakeTenant.TOKEN, *[PENDING] * 10)
    polled = asyncio.Event()

    async def sleep(_seconds: float) -> None:
        if fake_tenant.forms(FakeTenant.TOKEN):
            polled.set()
            await asyncio.Event().wait()  # parked until cancelled

    async def run() -> TokenGrant:
        async with Auth0OAuthClient(cli_settings(), transport=fake_tenant.transport) as client:
            return await device_sign_in(client, _request(), notify=lambda _m: None, sleep=sleep)

    task = asyncio.create_task(run())
    await asyncio.wait_for(polled.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 1


class RecordingStore(MemoryCredentialStore):
    instances: list["RecordingStore"] = []

    def __init__(self) -> None:
        super().__init__()
        RecordingStore.instances.append(self)


@pytest.mark.asyncio
@pytest.mark.parametrize("device", [True, False], ids=["device", "browser"])
async def test_an_ephemeral_session_lives_for_one_block_only(
    fake_tenant: FakeTenant, monkeypatch: pytest.MonkeyPatch, device: bool
) -> None:
    RecordingStore.instances = []
    monkeypatch.setattr(signin, "MemoryCredentialStore", RecordingStore)

    def no_persistent_store(_settings: CliSettings) -> None:
        raise AssertionError("an ephemeral session never opens the persistent store")

    monkeypatch.setattr("compose_api.cli.auth.storage.open_persistent_store", no_persistent_store)
    settings = cli_settings()
    if device:
        fake_tenant.queue(FakeTenant.DEVICE, fake_tenant.device_response(interval=1))
        fake_tenant.queue(FakeTenant.TOKEN, fake_tenant.token_response())  # offers a refresh token regardless
    request = SignInRequest(signup=True, provider=None, device=device, open_browser=True, persistent=True)

    async with ephemeral_session(
        settings, request, notify=lambda _m: None, launcher=FakeBrowser(fake_tenant), transport=fake_tenant.transport
    ) as record:
        [store] = RecordingStore.instances
        assert store.load(settings.binding_key(persistent=False)) == record
        assert record.identity.subject == fake_tenant.subject
        assert record.refresh_token is None, "no refresh token is kept for one command"
        assert OFFLINE_ACCESS_SCOPE not in record.scopes

    assert store.load(settings.binding_key(persistent=False)) is None, "the credentials are gone after the block"
    if device:
        assert OFFLINE_ACCESS_SCOPE not in fake_tenant.forms(FakeTenant.DEVICE)[0]["scope"]
    else:
        [authorize] = fake_tenant.authorize_requests
        assert OFFLINE_ACCESS_SCOPE not in authorize["scope"]
        assert "screen_hint" not in authorize, "an API command signs in; it never signs up"
    assert REFRESH_TOKEN  # the tenant offered one; see the assertion inside the block
