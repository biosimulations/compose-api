"""OAuth transport and token validation, against a fake tenant that signs real RS256 tokens."""

import base64
import hashlib
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from compose_api import authentication
from compose_api.cli.auth import oauth
from compose_api.cli.auth.models import AuthTransaction, SessionRecord, TokenGrant
from compose_api.cli.auth.oauth import Auth0OAuthClient
from compose_api.cli.config import OFFLINE_ACCESS_SCOPE, requested_scopes
from compose_api.cli.errors import AuthError, NetworkError, NotTransmitted, ProtocolError
from tests.fixtures.auth_fixtures import AUTH0_TEST_AUDIENCE, AUTH0_TEST_DOMAIN, AUTH0_TEST_ISSUER
from tests.fixtures.cli_fixtures import CLI_CLIENT_ID, DESCRIPTION_CANARY, REFRESH_TOKEN, FakeTenant, cli_settings

# Builds the token endpoint's answer for a transaction, given its nonce.
type Build = Callable[[FakeTenant, str], dict[str, Any] | httpx.Response]

FOREIGN_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
HMAC_KEY = "an-hmac-key-that-is-long-enough-for-hs256"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _now() -> int:
    return int(time.time())


def _transaction(*, persistent: bool = True) -> AuthTransaction:
    settings = cli_settings()
    return AuthTransaction(redirect_uri=settings.redirect_uri, scopes=requested_scopes(persistent=persistent))


async def _exchange(tenant: FakeTenant, build: Build, *, persistent: bool = True) -> TokenGrant:
    transaction = _transaction(persistent=persistent)
    tenant.queue(FakeTenant.TOKEN, build(tenant, transaction.nonce))
    async with Auth0OAuthClient(cli_settings(), transport=tenant.transport) as client:
        return await client.exchange_code(transaction, "code-1")


def _replace(body: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """`body` with fields replaced; a field given as None is removed."""
    merged = {**body, **fields}
    return {name: value for name, value in merged.items() if value is not None}


def _unsigned_claims(subject: str) -> dict[str, Any]:
    now = _now()
    return {"sub": subject, "iss": AUTH0_TEST_ISSUER, "aud": AUTH0_TEST_AUDIENCE, "iat": now, "exp": now + 300}


def test_the_client_enforces_the_same_contract_as_the_api() -> None:
    assert oauth.ALGORITHMS == authentication.ALLOWED_ALGORITHMS
    assert oauth.LEEWAY_SECONDS == authentication.JWT_LEEWAY_SECONDS


@pytest.mark.asyncio
async def test_code_exchange_yields_a_validated_grant(fake_tenant: FakeTenant) -> None:
    before = time.time()
    grant = await _exchange(fake_tenant, lambda t, nonce: t.token_response(nonce=nonce, expires_in=200))

    assert grant.identity.issuer == AUTH0_TEST_ISSUER
    assert grant.identity.subject == fake_tenant.subject
    assert grant.refresh_token == SecretStr(REFRESH_TOKEN)
    assert grant.scopes == ("openid", "profile", "email", OFFLINE_ACCESS_SCOPE)
    # The earlier of the JWT's exp (now + 300) and receipt + expires_in (now + 200).
    assert before + 199 <= grant.access_token_expires_at.timestamp() <= time.time() + 200

    [form] = fake_tenant.forms(FakeTenant.TOKEN)
    assert form.keys() == {"grant_type", "client_id", "code", "code_verifier", "redirect_uri"}
    assert (form["grant_type"], form["client_id"], form["code"]) == ("authorization_code", CLI_CLIENT_ID, "code-1")
    for request in fake_tenant.requests:
        assert request.url.host == AUTH0_TEST_DOMAIN
        assert "authorization" not in request.headers, "the CLI never sends a bearer or client credential to Auth0"
    assert str(fake_tenant.requests[0].url) == f"{AUTH0_TEST_ISSUER}.well-known/openid-configuration"


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [True, False])
async def test_authorization_url_carries_the_challenge_not_the_verifier(
    fake_tenant: FakeTenant, persistent: bool
) -> None:
    transaction = _transaction(persistent=persistent)
    async with Auth0OAuthClient(cli_settings(), transport=fake_tenant.transport) as client:
        plain = await client.authorization_url(transaction)
        hinted = await client.authorization_url(
            transaction, connection="google-oauth2", screen_hint="signup", prompt="login"
        )

    parts = urlsplit(plain)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{AUTH0_TEST_ISSUER}authorize"
    params = dict(parse_qsl(parts.query))
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(transaction.code_verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert params == {
        "response_type": "code",
        "client_id": CLI_CLIENT_ID,
        "redirect_uri": transaction.redirect_uri,
        "scope": " ".join(requested_scopes(persistent=persistent)),
        "state": transaction.state,
        "nonce": transaction.nonce,
        "audience": AUTH0_TEST_AUDIENCE,
        "code_challenge": expected_challenge,
        "code_challenge_method": "S256",
    }
    assert transaction.code_verifier not in plain
    assert (OFFLINE_ACCESS_SCOPE in params["scope"]) is persistent
    hinted_params = dict(parse_qsl(urlsplit(hinted).query))
    assert (hinted_params["connection"], hinted_params["screen_hint"], hinted_params["prompt"]) == (
        "google-oauth2",
        "signup",
        "login",
    )


def _hs256(t: FakeTenant, nonce: str) -> dict[str, Any]:
    token = jwt.encode(_unsigned_claims(t.subject), HMAC_KEY, algorithm="HS256", headers={"kid": "key-1"})
    return _replace(t.token_response(nonce=nonce), access_token=token)


def _alg_none(t: FakeTenant, nonce: str) -> dict[str, Any]:
    token = jwt.encode(_unsigned_claims(t.subject), "", algorithm="none", headers={"kid": "key-1"})
    return _replace(t.token_response(nonce=nonce), access_token=token)


REJECTED_GRANTS: list[tuple[str, Build, str]] = [
    # access token
    ("access-audience", lambda t, n: t.token_response(nonce=n, access={"aud": "https://other.api"}), "audience"),
    ("access-issuer", lambda t, n: t.token_response(nonce=n, access={"iss": "https://evil.example/"}), "tenant"),
    (
        "access-expired",
        lambda t, n: t.token_response(nonce=n, access={"iat": _now() - 7200, "exp": _now() - 3600}),
        "expired; check that this computer's clock",
    ),
    (
        "access-clock-skew",
        lambda t, n: t.token_response(nonce=n, access={"iat": _now() + 3600, "exp": _now() + 7200}),
        "not valid yet; check that this computer's clock",
    ),
    ("access-no-sub", lambda t, n: t.token_response(nonce=n, access={"sub": None}), "no 'sub' claim"),
    ("access-no-exp", lambda t, n: t.token_response(nonce=n, access={"exp": None}), "no 'exp' claim"),
    ("access-no-iat", lambda t, n: t.token_response(nonce=n, access={"iat": None}), "no 'iat' claim"),
    ("access-hs256", _hs256, "not signed with RS256"),
    ("access-alg-none", _alg_none, "not signed with RS256"),
    (
        "access-foreign-key",
        lambda t, n: t.token_response(nonce=n, access={"signing_key": FOREIGN_KEY}),
        "signature does not verify",
    ),
    (
        "access-unknown-kid",
        lambda t, n: t.token_response(nonce=n, access={"kid": "key-9", "signing_key": FOREIGN_KEY}),
        "key the tenant does not publish",
    ),
    (
        "access-opaque",
        lambda t, n: _replace(t.token_response(nonce=n), access_token="opaque-access-token"),  # noqa: S106 -- test data
        "not a signed JWT; check auth0_audience",
    ),
    # ID token
    ("id-audience", lambda t, n: t.token_response(nonce=n, id_token={"aud": "OtherClient"}), "audience"),
    (
        "id-extra-audience-no-azp",
        lambda t, n: t.token_response(nonce=n, id_token={"aud": [CLI_CLIENT_ID, "OtherClient"]}),
        "'azp' claim is missing",
    ),
    ("id-azp", lambda t, n: t.token_response(nonce=n, id_token={"azp": "OtherClient"}), "'azp' claim is invalid"),
    ("id-no-nonce", lambda t, n: t.token_response(nonce=None), "'nonce' claim is missing"),
    ("id-wrong-nonce", lambda t, n: t.token_response(nonce="replayed"), "'nonce' claim is invalid"),
    ("id-issuer", lambda t, n: t.token_response(nonce=n, id_token={"iss": "https://evil.example/"}), "tenant"),
    (
        "id-expired",
        lambda t, n: t.token_response(nonce=n, id_token={"iat": _now() - 7200, "exp": _now() - 3600}),
        "expired",
    ),
    ("id-other-user", lambda t, n: t.token_response(nonce=n, id_token={"sub": "auth0|other"}), "different users"),
    (
        "id-foreign-key",
        lambda t, n: t.token_response(nonce=n, id_token={"signing_key": FOREIGN_KEY}),
        "signature does not verify",
    ),
    ("id-at-hash", lambda t, n: t.token_response(nonce=n, id_token={"at_hash": "AAAA"}), "'at_hash' claim is invalid"),
    ("id-missing", lambda t, n: t.token_response(nonce=n, include_id_token=False), "no ID token"),
    # response fields
    ("token-type", lambda t, n: _replace(t.token_response(nonce=n), token_type="mac"), "not a Bearer token"),  # noqa: S106 -- test data
    ("no-token-type", lambda t, n: _replace(t.token_response(nonce=n), token_type=None), "not a Bearer token"),
    ("no-expires-in", lambda t, n: _replace(t.token_response(nonce=n), expires_in=None), "expires_in"),
    ("string-expires-in", lambda t, n: t.token_response(nonce=n, expires_in="300"), "expires_in"),
    ("float-expires-in", lambda t, n: t.token_response(nonce=n, expires_in=300.5), "expires_in"),
    ("bool-expires-in", lambda t, n: t.token_response(nonce=n, expires_in=True), "expires_in"),
    ("zero-expires-in", lambda t, n: t.token_response(nonce=n, expires_in=0), "expires_in"),
    ("negative-expires-in", lambda t, n: t.token_response(nonce=n, expires_in=-60), "expires_in"),
    ("huge-expires-in", lambda t, n: t.token_response(nonce=n, expires_in=10**9), "expires_in"),
    ("short-lived", lambda t, n: t.token_response(nonce=n, expires_in=30), "expires within a minute"),
    ("no-access-token", lambda t, n: _replace(t.token_response(nonce=n), access_token=None), "access_token"),
    ("empty-access-token", lambda t, n: _replace(t.token_response(nonce=n), access_token=""), "access_token"),
    ("numeric-access-token", lambda t, n: _replace(t.token_response(nonce=n), access_token=42), "access_token"),
    ("scope-type", lambda t, n: _replace(t.token_response(nonce=n), scope=42), "malformed scope"),
    ("empty-scope", lambda t, n: t.token_response(nonce=n, scope=" "), "malformed scope"),
    ("no-openid", lambda t, n: t.token_response(nonce=n, scope="profile email"), "openid"),
    ("empty-refresh", lambda t, n: t.token_response(nonce=n, refresh_token=""), "refresh_token"),
    ("numeric-refresh", lambda t, n: _replace(t.token_response(nonce=n), refresh_token=7), "refresh_token"),
    ("not-an-object", lambda t, n: httpx.Response(200, json=[t.token_response(nonce=n)]), "malformed response"),
    ("not-json", lambda t, n: httpx.Response(200, text="<html>"), "malformed response"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("build", "fragment"), [(b, f) for _, b, f in REJECTED_GRANTS], ids=[i for i, _, _ in REJECTED_GRANTS]
)
async def test_invalid_grants_are_rejected_whole(fake_tenant: FakeTenant, build: Build, fragment: str) -> None:
    built: list[dict[str, Any] | httpx.Response] = []

    def recording(t: FakeTenant, nonce: str) -> dict[str, Any] | httpx.Response:
        built.append(build(t, nonce))
        return built[-1]

    with pytest.raises(ProtocolError) as caught:
        await _exchange(fake_tenant, recording)
    assert fragment in caught.value.message
    [body] = built
    if isinstance(body, dict):
        for field in ("access_token", "id_token", "refresh_token"):
            value = body.get(field)
            if isinstance(value, str) and value:
                assert value not in caught.value.message


@pytest.mark.asyncio
async def test_omitted_scope_means_the_requested_scope(fake_tenant: FakeTenant) -> None:
    grant = await _exchange(fake_tenant, lambda t, nonce: t.token_response(nonce=nonce, scope=None))
    assert grant.scopes == requested_scopes(persistent=True)


@pytest.mark.asyncio
async def test_a_one_command_session_never_keeps_a_refresh_token(fake_tenant: FakeTenant) -> None:
    grant = await _exchange(fake_tenant, lambda t, nonce: t.token_response(nonce=nonce), persistent=False)
    assert grant.refresh_token is None
    assert OFFLINE_ACCESS_SCOPE not in grant.scopes, "nor does it claim offline access it did not ask for"


@pytest.mark.asyncio
async def test_a_persistent_sign_in_without_a_refresh_token_keeps_the_access_token(fake_tenant: FakeTenant) -> None:
    grant = await _exchange(fake_tenant, lambda t, nonce: t.token_response(nonce=nonce, refresh_token=None))
    assert grant.refresh_token is None
    assert grant.access_token.get_secret_value()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error", "fragment"),
    [
        (
            httpx.Response(403, json={"error": "invalid_grant", "error_description": DESCRIPTION_CANARY}),
            AuthError,
            "invalid_grant",
        ),
        (httpx.Response(429, json={"error": "too_many_requests"}), NetworkError, "rate limiting"),
        (httpx.Response(503), NetworkError, "HTTP 503"),
        (
            httpx.Response(401, json={"error": "unauthorized_client", "error_description": DESCRIPTION_CANARY}),
            ProtocolError,
            "unauthorized_client",
        ),
        (httpx.Response(400, text=DESCRIPTION_CANARY), ProtocolError, "HTTP 400"),
        (httpx.Response(400, json={"error": "bad\x1b[31mcode"}), ProtocolError, "HTTP 400"),
        (httpx.Response(302, headers={"Location": "https://evil.example/token"}), ProtocolError, "redirect"),
        (httpx.Response(200, content=b"{" + b" " * oauth.MAX_RESPONSE_BYTES + b"}"), ProtocolError, "large"),
    ],
)
async def test_token_endpoint_failures_are_reported_without_server_text(
    fake_tenant: FakeTenant, response: httpx.Response, error: type[Exception], fragment: str
) -> None:
    with pytest.raises(error) as caught:
        await _exchange(fake_tenant, lambda _t, _nonce: response)
    message = str(caught.value)
    assert fragment in message
    assert DESCRIPTION_CANARY not in message and "\x1b" not in message
    assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 1, "a code is redeemed at most once, and redirects not followed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "fragment"),
    [(httpx.ConnectError("refused"), "could not reach Auth0"), (httpx.ReadTimeout("slow"), "did not answer in time")],
)
async def test_transport_failures_are_network_errors(failure: httpx.HTTPError, fragment: str) -> None:
    def broken(_request: httpx.Request) -> httpx.Response:
        raise failure

    async with Auth0OAuthClient(cli_settings(), transport=httpx.MockTransport(broken)) as client:
        with pytest.raises(NetworkError, match=fragment):
            await client.metadata()


DISCOVERY_DEFECTS: list[tuple[str, dict[str, Any], str]] = [
    ("issuer", {"issuer": "https://evil.example/"}, "different issuer"),
    ("trailing-issuer", {"issuer": AUTH0_TEST_ISSUER.rstrip("/")}, "different issuer"),
    ("foreign-token", {"token_endpoint": "https://evil.example/oauth/token"}, "token_endpoint"),
    ("lookalike-host", {"jwks_uri": f"https://{AUTH0_TEST_DOMAIN}.evil.example/jwks"}, "jwks_uri"),
    ("http", {"authorization_endpoint": f"http://{AUTH0_TEST_DOMAIN}/authorize"}, "authorization_endpoint"),
    ("userinfo", {"token_endpoint": f"https://u:p@{AUTH0_TEST_DOMAIN}/oauth/token"}, "token_endpoint"),
    ("port", {"token_endpoint": f"https://{AUTH0_TEST_DOMAIN}:8443/oauth/token"}, "token_endpoint"),
    ("query", {"authorization_endpoint": f"{AUTH0_TEST_ISSUER}authorize?x=1"}, "authorization_endpoint"),
    ("missing-jwks", {"jwks_uri": None}, "no jwks_uri"),
    ("numeric-endpoint", {"token_endpoint": 5}, "malformed token_endpoint"),
    ("no-s256", {"code_challenge_methods_supported": ["plain"]}, "S256"),
    ("no-rs256", {"id_token_signing_alg_values_supported": ["HS256"]}, "RS256"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "fragment"), [(c, f) for _, c, f in DISCOVERY_DEFECTS], ids=[i for i, _, _ in DISCOVERY_DEFECTS]
)
async def test_discovery_is_trusted_only_for_the_configured_tenant(
    fake_tenant: FakeTenant, changes: dict[str, Any], fragment: str
) -> None:
    fake_tenant.discovery = _replace(fake_tenant.discovery, **changes)
    async with Auth0OAuthClient(cli_settings(), transport=fake_tenant.transport) as client:
        with pytest.raises(ProtocolError, match=fragment):
            await client.metadata()
    assert len(fake_tenant.requests) == 1, "nothing is fetched from an untrusted discovery document"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(404), ProtocolError),
        (httpx.Response(503), NetworkError),
        (httpx.Response(200, json=[]), ProtocolError),
    ],
)
async def test_discovery_failures(response: httpx.Response, error: type[Exception]) -> None:
    async with Auth0OAuthClient(cli_settings(), transport=httpx.MockTransport(lambda _r: response)) as client:
        with pytest.raises(error):
            await client.metadata()


@pytest.mark.asyncio
async def test_signing_keys_outage_yields_no_grant(fake_tenant: FakeTenant) -> None:
    fake_tenant.auth0.jwks_available = False
    with pytest.raises(NetworkError, match="HTTP 503"):
        await _exchange(fake_tenant, lambda t, nonce: t.token_response(nonce=nonce))


@pytest.mark.asyncio
async def test_key_rotation_is_picked_up_without_refetching_on_every_unknown_key(fake_tenant: FakeTenant) -> None:
    clock = FakeClock()
    settings = cli_settings()
    async with Auth0OAuthClient(settings, transport=fake_tenant.transport, monotonic=clock) as client:

        async def exchange(kid: str) -> TokenGrant:
            transaction = AuthTransaction(redirect_uri=settings.redirect_uri, scopes=requested_scopes(persistent=True))
            claims = {"kid": kid}
            fake_tenant.queue(
                FakeTenant.TOKEN, fake_tenant.token_response(nonce=transaction.nonce, access=claims, id_token=claims)
            )
            return await client.exchange_code(transaction, "code")

        await exchange("key-1")
        fake_tenant.auth0.add_key("key-2")
        with pytest.raises(ProtocolError, match="key the tenant does not publish"):
            await exchange("key-2")  # the keys were fetched moments ago, so an unknown kid does not refetch
        assert fake_tenant.auth0.jwks_requests == 1
        clock.now += oauth.JWKS_MIN_REFRESH_INTERVAL_SECONDS
        assert (await exchange("key-2")).identity.subject == fake_tenant.subject
        assert fake_tenant.auth0.jwks_requests == 2


@pytest.mark.asyncio
async def test_refresh_discovery_failure_does_not_send_the_token(fake_tenant: FakeTenant) -> None:
    async with Auth0OAuthClient(cli_settings(), transport=fake_tenant.transport) as client:

        async def unreachable() -> oauth.ProviderMetadata:
            raise NetworkError("could not reach Auth0")

        client.metadata = unreachable  # type: ignore[method-assign]
        with pytest.raises(NotTransmitted) as excinfo:
            await client.refresh(SecretStr(REFRESH_TOKEN), requested_scopes(persistent=True))
    assert isinstance(excinfo.value.cause, NetworkError)
    assert fake_tenant.forms(FakeTenant.TOKEN) == []


@pytest.mark.asyncio
async def test_refresh_returns_exactly_what_auth0_sent(fake_tenant: FakeTenant) -> None:
    scopes = requested_scopes(persistent=True)
    fake_tenant.queue(
        FakeTenant.TOKEN,
        fake_tenant.token_response(refresh_token="rt-rotated", include_id_token=False),  # noqa: S106 -- test data
        fake_tenant.token_response(refresh_token=None, include_id_token=False),
    )
    async with Auth0OAuthClient(cli_settings(), transport=fake_tenant.transport) as client:
        rotated = await client.refresh(SecretStr(REFRESH_TOKEN), scopes)
        omitted = await client.refresh(SecretStr("rt-rotated"), scopes)
    assert rotated.refresh_token == SecretStr("rt-rotated")
    assert omitted.refresh_token is None, "a spent refresh token is never carried forward"
    assert fake_tenant.forms(FakeTenant.TOKEN)[0] == {
        "grant_type": "refresh_token",
        "client_id": CLI_CLIENT_ID,
        "refresh_token": REFRESH_TOKEN,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error", "fragment"),
    [
        (httpx.Response(403, json={"error": "invalid_grant"}), AuthError, "invalid_grant"),
        (None, ProtocolError, "different users"),
    ],
)
async def test_refresh_failures(
    fake_tenant: FakeTenant, response: httpx.Response | None, error: type[Exception], fragment: str
) -> None:
    fake_tenant.queue(
        FakeTenant.TOKEN, response or fake_tenant.token_response(id_token={"sub": "auth0|other"}, nonce=None)
    )
    async with Auth0OAuthClient(cli_settings(), transport=fake_tenant.transport) as client:
        with pytest.raises(error, match=fragment):
            await client.refresh(SecretStr(REFRESH_TOKEN), requested_scopes(persistent=True))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [(httpx.Response(200), None), (httpx.Response(503), NetworkError), (httpx.Response(400), ProtocolError)],
)
async def test_revocation(fake_tenant: FakeTenant, response: httpx.Response, error: type[Exception] | None) -> None:
    fake_tenant.queue(FakeTenant.REVOKE, response)
    async with Auth0OAuthClient(cli_settings(), transport=fake_tenant.transport) as client:
        if error is None:
            await client.revoke(SecretStr(REFRESH_TOKEN))
        else:
            with pytest.raises(error):
                await client.revoke(SecretStr(REFRESH_TOKEN))
    assert fake_tenant.forms(FakeTenant.REVOKE) == [
        {"client_id": CLI_CLIENT_ID, "token": REFRESH_TOKEN, "token_type_hint": "refresh_token"}
    ]


@pytest.mark.asyncio
async def test_revocation_needs_an_advertised_endpoint(fake_tenant: FakeTenant) -> None:
    fake_tenant.discovery.pop("revocation_endpoint")
    async with Auth0OAuthClient(cli_settings(), transport=fake_tenant.transport) as client:
        with pytest.raises(ProtocolError, match="revocation"):
            await client.revoke(SecretStr(REFRESH_TOKEN))
    assert fake_tenant.forms(FakeTenant.REVOKE) == []


@pytest.mark.asyncio
async def test_secrets_never_reach_a_repr_dump_or_log(
    fake_tenant: FakeTenant, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    transaction = _transaction()
    body = fake_tenant.token_response(nonce=transaction.nonce)
    fake_tenant.queue(FakeTenant.TOKEN, body)
    async with Auth0OAuthClient(cli_settings(), transport=fake_tenant.transport) as client:
        grant = await client.exchange_code(transaction, "code-LEAK-CANARY-0")
    record = SessionRecord.from_grant(grant, binding_key="k")

    secrets = [
        body["access_token"],
        body["id_token"],
        REFRESH_TOKEN,
        "code-LEAK-CANARY-0",
        transaction.code_verifier,
        transaction.state,
        transaction.nonce,
    ]
    shown = " ".join([
        repr(grant),
        str(grant),
        grant.model_dump_json(),
        repr(record),
        record.model_dump_json(),
        repr(transaction),
    ])
    logged = caplog.text
    for secret in secrets:
        assert secret not in shown
        assert secret not in logged


def test_the_http_client_follows_no_redirects_and_ignores_the_environment() -> None:
    client = Auth0OAuthClient(cli_settings())
    assert client._http.follow_redirects is False
    assert client._http._trust_env is False
    timeout = client._http.timeout
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (5.0, 15.0, 15.0, 15.0)
