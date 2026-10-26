"""The API boundary: the generated client against the real app over ASGI, carrying real signed tokens."""

import asyncio
import io
import re
import ssl
import zipfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from compose_api_client.auth.oauth import Auth0OAuthClient
from compose_api_client.auth.session import AuthSession
from compose_api_client.auth.sources import AsyncStoredSession, OneCommandSession, SyncStoredSession
from compose_api_client.auth.storage import MemoryCredentialStore
from compose_api_client.ext._policy import CURRENT_PRINCIPAL
from compose_api_client.ext.credentials import EnvironmentToken
from compose_api_client.ext.errors import (
    ApiError,
    AuthError,
    ConfigError,
    ExitCode,
    ForbiddenError,
    InvalidRequestError,
    NetworkError,
    NotFoundError,
    ProtocolError,
    RateLimitedError,
    ServerError,
    UncertainOutcomeError,
)
from compose_api_client.ext.session import AsyncComposeSession, ComposeSession
from compose_api_client.models import JobStatus
from compose_api_client.profiles import CliSettings
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from compose_api.api.main import app
from compose_api.authentication import Auth0Verifier, JwksCache, get_auth0_verifier
from tests.fixtures.auth_fixtures import AUTH0_TEST_DOMAIN, AUTH0_TEST_ISSUER, FakeAuth0
from tests.fixtures.cli_fixtures import (
    DESCRIPTION_CANARY,
    FakeComposeApi,
    FakeTenant,
    RecordingTransport,
    SyncOverAsyncTransport,
    cli_settings,
    seed_session,
)

API = "https://api.compose.test"
FOREIGN_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
# The API cannot verify this, but the session layer has no reason to doubt a token it already accepted.
REJECTED = {"signing_key": FOREIGN_KEY}


def _settings(**overrides: Any) -> CliSettings:
    return cli_settings(callback_port=8400, **overrides)


def _archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.xml", "<omexManifest/>")
    return buffer.getvalue()


def _renewal(tenant: FakeTenant) -> None:
    tenant.queue(FakeTenant.TOKEN, tenant.token_response(refresh_token="rt-rotated", include_id_token=False))  # noqa: S106 -- test data


Session = ComposeSession | AsyncComposeSession


async def invoke(api: Session, method: str, *args: Any, **kwargs: Any) -> Any:
    call = getattr(api, method)
    if isinstance(api, AsyncComposeSession):
        return await call(*args, **kwargs)
    return await asyncio.to_thread(call, *args, **kwargs)


@asynccontextmanager
async def stored_api(
    settings: CliSettings,
    tenant: FakeTenant,
    transport: httpx.AsyncBaseTransport,
    store: MemoryCredentialStore,
    session_kind: str,
) -> AsyncIterator[Session]:
    session = AuthSession(settings, store)
    if session_kind == "sync":
        api = ComposeSession(
            settings.api_base_url,
            tokens=SyncStoredSession(settings, session, auth0_transport=tenant.transport),
            transport=SyncOverAsyncTransport(transport),
            ca_bundle=settings.ca_bundle,
        )
        try:
            yield api
        finally:
            await asyncio.to_thread(api.close)
    else:
        async with (
            Auth0OAuthClient(settings, transport=tenant.transport) as oauth,
            AsyncComposeSession(
                settings.api_base_url,
                tokens=AsyncStoredSession(session, oauth),
                transport=transport,
                ca_bundle=settings.ca_bundle,
            ) as api_async,
        ):
            yield api_async


pytestmark = pytest.mark.parametrize("session_kind", ["sync", "async"])


def _mock(handler: Callable[[httpx.Request], httpx.Response]) -> RecordingTransport:
    return RecordingTransport(httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_the_api_verifies_the_session_with_real_signed_tokens(
    session_kind: str, fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    record = await seed_session(settings, fake_tenant, store)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store, session_kind) as api:
        principal = await invoke(api, "whoami")

    assert (principal.issuer, principal.subject) == (AUTH0_TEST_ISSUER, fake_tenant.subject)
    assert "user" in principal.roles
    [request] = fake_compose_api.transport.requests
    assert str(request.url) == f"{API}/auth/me"
    assert request.headers["authorization"] == f"Bearer {record.access_token.get_secret_value()}"
    stored = store.load(settings.binding_key(persistent=True))
    assert stored is not None and stored.api_verified_at is not None
    assert fake_tenant.requests == [], "a valid session needs nothing from Auth0"
    assert fake_compose_api.transport.closed == 1


@pytest.mark.asyncio
async def test_catalog_status_and_submit_through_the_real_routes(
    session_kind: str, fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    archive = _archive()
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store, session_kind) as api:
        simulators = await invoke(api, "simulators")
        run = await invoke(api, "status", FakeComposeApi.SIMULATION_ID)
        experiment = await invoke(api, "submit", archive, interval=2.5, batch=True)
        await invoke(api, "submit", archive)

    [version] = simulators.versions
    assert (version.database_id, version.container_def_hash) == (7, "0123456789abcdef0123456789abcdef")
    assert run.record is not None
    assert (run.record.sim_id, run.status) == (FakeComposeApi.SIMULATION_ID, JobStatus.RUNNING)
    assert experiment.simulation_database_id == FakeComposeApi.SIMULATION_ID
    # The generated multipart encoding, parsed by the real route: every byte, the name and both query parameters.
    assert fake_compose_api.uploads == [
        {"file_name": "upload", "content": archive, "batch": True, "interval_time": 2.5},
        {"file_name": "upload", "content": archive, "batch": False, "interval_time": 1.0},
    ]
    assert fake_compose_api.created == 2
    assert fake_compose_api.transport.closed == 1, "one session client is reused across all four requests"


@pytest.mark.asyncio
async def test_a_rejected_read_is_renewed_once_and_replayed_once(
    session_kind: str, fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    first = await seed_session(settings, fake_tenant, store, access=REJECTED)
    _renewal(fake_tenant)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store, session_kind) as api:
        simulators = await invoke(api, "simulators")

    assert simulators.versions
    assert fake_compose_api.transport.paths() == ["/core/simulator/list"] * 2
    assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 1
    renewed = store.load(settings.binding_key(persistent=True))
    assert renewed is not None and renewed.generation == first.generation + 1
    assert fake_compose_api.transport.closed == 2, (
        "the rejected token's client is closed when replaced, then the renewed one on exit"
    )
    for request in fake_tenant.requests:
        assert "authorization" not in request.headers, "the bearer never goes to Auth0"


@pytest.mark.asyncio
async def test_a_second_rejection_is_final_and_points_at_the_profile(
    session_kind: str, fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi, fake_auth0: FakeAuth0
) -> None:
    jwks = JwksCache(f"{AUTH0_TEST_ISSUER}.well-known/jwks.json", transport=httpx.MockTransport(fake_auth0.handle_jwks))
    elsewhere = Auth0Verifier(domain=AUTH0_TEST_DOMAIN, audience="https://elsewhere.test", jwks=jwks)
    app.dependency_overrides[get_auth0_verifier] = lambda: elsewhere
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    _renewal(fake_tenant)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store, session_kind) as api:
        with pytest.raises(AuthError, match=r"even after renewing the session.*auth0_audience"):
            await invoke(api, "simulators")
    assert fake_compose_api.transport.paths() == ["/core/simulator/list"] * 2
    assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 1


@pytest.mark.asyncio
async def test_a_one_command_session_cannot_be_renewed(
    session_kind: str, fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    record = await seed_session(settings, fake_tenant, store, access=REJECTED)
    source = OneCommandSession(record)
    api: Session = (
        ComposeSession(
            API, tokens=source.as_sync_source(), transport=SyncOverAsyncTransport(fake_compose_api.transport)
        )
        if session_kind == "sync"
        else AsyncComposeSession(API, tokens=source.as_async_source(), transport=fake_compose_api.transport)
    )
    try:
        with pytest.raises(AuthError, match="cannot be renewed"):
            await invoke(api, "simulators")
    finally:
        await invoke(api, "close" if session_kind == "sync" else "aclose")
    assert fake_compose_api.transport.paths() == ["/core/simulator/list"]


@pytest.mark.asyncio
async def test_a_rejected_submission_is_never_replayed(
    session_kind: str, fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    first = await seed_session(settings, fake_tenant, store, access=REJECTED)
    _renewal(fake_tenant)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store, session_kind) as api:
        with pytest.raises(AuthError, match="was not submitted; the session was renewed, so run the command again"):
            await invoke(api, "submit", _archive())
    assert fake_compose_api.transport.paths() == ["/simulation/run"]
    assert fake_compose_api.created == 0
    renewed = store.load(settings.binding_key(persistent=True))
    assert renewed is not None and renewed.generation == first.generation + 1, "ready for the next invocation"


@pytest.mark.asyncio
async def test_forbidden_is_final_and_never_renews(session_kind: str, fake_tenant: FakeTenant) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    transport = _mock(lambda _request: httpx.Response(403, json={"detail": DESCRIPTION_CANARY}))
    async with stored_api(settings, fake_tenant, transport, store, session_kind) as api:
        with pytest.raises(ForbiddenError, match="signing in again will not change that") as caught:
            await invoke(api, "simulators")
    assert caught.value.exit_code == ExitCode.FORBIDDEN
    assert len(transport.requests) == 1 and fake_tenant.forms(FakeTenant.TOKEN) == []
    assert DESCRIPTION_CANARY not in caught.value.message


def _validation(loc: list[Any]) -> dict[str, Any]:
    return {"detail": [{"loc": loc, "msg": DESCRIPTION_CANARY, "type": "value_error", "input": DESCRIPTION_CANARY}]}


FAILURES: list[tuple[str, str, httpx.Response, type[Exception], str]] = [
    ("list-404", "list", httpx.Response(404, json={"detail": DESCRIPTION_CANARY}), NotFoundError, "HTTP 404"),
    (
        "status-422",
        "status",
        httpx.Response(422, json=_validation(["query", "simulation_id"])),
        InvalidRequestError,
        r"invalid \(query.simulation_id\) \(HTTP 422",
    ),
    (
        "status-422-hostile-field",
        "status",
        httpx.Response(422, json=_validation(["query", "x\x1b[2J"])),
        InvalidRequestError,
        r"invalid \(HTTP 422",
    ),
    ("submit-400", "submit", httpx.Response(400, json={"detail": DESCRIPTION_CANARY}), InvalidRequestError, "HTTP 400"),
    ("429-seconds", "list", httpx.Response(429, headers={"Retry-After": "120"}), RateLimitedError, "retry after 120 s"),
    (
        "429-date",
        "list",
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        RateLimitedError,
        "wait a little",
    ),
    ("429-huge", "list", httpx.Response(429, headers={"Retry-After": "99999999"}), RateLimitedError, "wait a little"),
    ("503", "list", httpx.Response(503, text=DESCRIPTION_CANARY), NetworkError, "unavailable"),
    ("500", "status", httpx.Response(500, text=DESCRIPTION_CANARY), ServerError, "HTTP 500"),
    ("submit-500", "submit", httpx.Response(500), UncertainOutcomeError, "may or may not have been created"),
    ("599", "list", httpx.Response(599), ServerError, "HTTP 599"),
    ("418", "list", httpx.Response(418), ApiError, "HTTP 418"),
    (
        "redirect",
        "list",
        httpx.Response(307, headers={"Location": "https://evil.example/core/simulator/list"}),
        ProtocolError,
        "never sent to a redirect",
    ),
    ("not-json", "list", httpx.Response(200, text=DESCRIPTION_CANARY), ProtocolError, "could not be read"),
    (
        "wrong-shape",
        "status",
        httpx.Response(200, json={"detail": DESCRIPTION_CANARY}),
        ProtocolError,
        "could not be read",
    ),
    (
        "submit-unreadable",
        "submit",
        httpx.Response(200, text="{"),
        UncertainOutcomeError,
        "may or may not have been created",
    ),
]


async def _operation(api: Session, name: str) -> object:
    if name == "list":
        return await invoke(api, "simulators")
    if name == "status":
        return await invoke(api, "status", 5)
    return await invoke(api, "submit", _archive())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "response", "error", "fragment"),
    [case[1:] for case in FAILURES],
    ids=[case[0] for case in FAILURES],
)
async def test_every_status_is_interpreted_before_a_body_is_trusted(
    session_kind: str,
    fake_tenant: FakeTenant,
    operation: str,
    response: httpx.Response,
    error: type[Exception],
    fragment: str,
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    transport = _mock(lambda _request: response)
    async with stored_api(settings, fake_tenant, transport, store, session_kind) as api:
        with pytest.raises(error, match=fragment) as caught:
            await _operation(api, operation)
    message = str(caught.value)
    assert DESCRIPTION_CANARY not in message and "\x1b" not in message
    assert len(transport.requests) == 1, "nothing is retried or followed"
    assert fake_tenant.forms(FakeTenant.TOKEN) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "failure", "fragment", "unknown_outcome"),
    [
        ("submit", httpx.ConnectError("refused"), "could not connect", False),
        ("submit", httpx.ReadTimeout("slow"), "did not answer in time", True),
        ("submit", httpx.RemoteProtocolError("cut"), "connection failed", True),
        ("list", httpx.ReadTimeout("slow"), "did not answer in time", False),
    ],
)
async def test_transport_failures_are_never_retried(
    session_kind: str,
    fake_tenant: FakeTenant,
    operation: str,
    failure: httpx.HTTPError,
    fragment: str,
    unknown_outcome: bool,
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)

    def broken(_request: httpx.Request) -> httpx.Response:
        raise failure

    transport = _mock(broken)
    async with stored_api(settings, fake_tenant, transport, store, session_kind) as api:
        with pytest.raises(UncertainOutcomeError if unknown_outcome else NetworkError, match=fragment) as caught:
            await _operation(api, operation)
    assert ("may or may not have been created" in caught.value.message) is unknown_outcome
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_a_session_about_to_expire_is_renewed_before_the_request(
    session_kind: str, fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store, expires_in=30)
    _renewal(fake_tenant)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store, session_kind) as api:
        await invoke(api, "whoami")
        await invoke(api, "simulators")
    assert fake_compose_api.transport.paths() == ["/auth/me", "/core/simulator/list"], "no 401 round trip"
    assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 1
    stored = store.load(settings.binding_key(persistent=True))
    assert stored is not None and stored.api_verified_at is not None


@pytest.mark.asyncio
async def test_a_confirmation_survives_renewal(
    session_kind: str, fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store, session_kind) as api:
        await invoke(api, "whoami")
    confirmed = store.load(settings.binding_key(persistent=True))
    assert confirmed is not None and confirmed.api_verified_at is not None
    session = AuthSession(settings, store)
    _renewal(fake_tenant)
    async with Auth0OAuthClient(settings, transport=fake_tenant.transport) as oauth:
        renewed = await session.get_access_token(oauth, rejected_generation=confirmed.generation)
    assert renewed.generation == confirmed.generation + 1
    assert renewed.api_verified_at == confirmed.api_verified_at, (
        "renewal keeps the identity, so the confirmation stands"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["subject", "issuer"])
async def test_an_api_that_names_someone_else_is_not_believed(
    session_kind: str, fake_tenant: FakeTenant, mismatch: str
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    principal = {
        "issuer": AUTH0_TEST_ISSUER,
        "subject": fake_tenant.subject,
        "audience": [],
        "roles": ["user"],
        "scopes": [],
        "permissions": [],
    }
    principal[mismatch] = "someone-else"
    transport = _mock(lambda _request: httpx.Response(200, json=principal))
    async with stored_api(settings, fake_tenant, transport, store, session_kind) as api:
        with pytest.raises(ProtocolError, match="different user"):
            await invoke(api, "whoami")
    stored = store.load(settings.binding_key(persistent=True))
    assert stored is not None and stored.api_verified_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/auth/me",
        "https://api.compose.test.evil.example/auth/me",
        "https://api.compose.test:8443/auth/me",
        "http://api.compose.test/auth/me",
        "https://user:pw@api.compose.test/auth/me",
        f"https://{AUTH0_TEST_DOMAIN}/auth/me",
        "https://api.compose.test/not-in-spec",
        "https://api.compose.test/",
    ],
)
@pytest.mark.parametrize("credential_source", ["stored", "environment"])
async def test_credentials_go_only_to_this_profiles_api_operations(
    session_kind: str, fake_tenant: FakeTenant, url: str, credential_source: str
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    transport = _mock(lambda _request: httpx.Response(200))
    async with stored_api(settings, fake_tenant, transport, store, session_kind) as api:
        if credential_source == "environment":
            env = EnvironmentToken("guard-test-token")
            if isinstance(api, AsyncComposeSession):
                api.tokens = env.as_async()
            else:
                api.tokens = env
        if isinstance(api, AsyncComposeSession):

            async def wander(client: Any) -> Any:
                return await client.get_async_httpx_client().get(url)

            with pytest.raises(ProtocolError, match="refused to send credentials"):
                await api._send(CURRENT_PRINCIPAL, wander)
        else:

            def wander_sync(client: Any) -> Any:
                return client.get_httpx_client().get(url)

            with pytest.raises(ProtocolError, match="refused to send credentials"):
                await asyncio.to_thread(api._send, CURRENT_PRINCIPAL, wander_sync)
    assert transport.requests == [], "the request never left"


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["static-token", None])
async def test_an_api_url_with_its_default_port_still_reaches_the_api(session_kind: str, token: str | None) -> None:
    # httpx sends `https://api.compose.test:443` as `https://api.compose.test`; the guard must not take that for
    # another server and refuse every request, signed in or not.
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(answer)
    if session_kind == "sync":
        api = ComposeSession(f"{API}:443", token=token, transport=transport)
        try:
            response, _ = await asyncio.to_thread(
                api._send, CURRENT_PRINCIPAL, lambda client: client.get_httpx_client().get("/auth/me")
            )
        finally:
            api.close()
    else:
        async with AsyncComposeSession(f"{API}:443", token=token, transport=transport) as api_async:

            async def get(client: Any) -> Any:
                return await client.get_async_httpx_client().get("/auth/me")

            response, _ = await api_async._send(CURRENT_PRINCIPAL, get)
    assert response.status_code == 200
    [request] = sent
    assert str(request.url) == f"{API}/auth/me"
    assert ("authorization" in request.headers) is (token is not None)


@pytest.mark.asyncio
async def test_an_anonymous_request_elsewhere_is_refused_without_mentioning_credentials(session_kind: str) -> None:
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(answer)
    elsewhere = "https://evil.example/auth/me"
    if session_kind == "sync":
        api = ComposeSession(API, transport=transport)
        try:
            with pytest.raises(ProtocolError) as caught:
                await asyncio.to_thread(
                    api._send, CURRENT_PRINCIPAL, lambda client: client.get_httpx_client().get(elsewhere)
                )
        finally:
            api.close()
    else:
        async with AsyncComposeSession(API, transport=transport) as api_async:

            async def wander(client: Any) -> Any:
                return await client.get_async_httpx_client().get(elsewhere)

            with pytest.raises(ProtocolError) as caught:
                await api_async._send(CURRENT_PRINCIPAL, wander)
    assert str(caught.value) == f"refused to send a request for GET /auth/me anywhere but {API}"
    assert sent == [], "the request never left"


def _self_signed_certificate(path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "compose-api-local test CA")])
    now = datetime.now(UTC)
    certificate = (
        x509
        .CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now.replace(year=now.year + 1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def test_a_ca_bundle_extends_tls_trust_and_a_bad_one_is_a_configuration_error(
    session_kind: str, tmp_path: Path
) -> None:
    good, bad = tmp_path / "ca.pem", tmp_path / "bad.pem"
    _self_signed_certificate(good)
    bad.write_text("not a certificate")
    cls = ComposeSession if session_kind == "sync" else AsyncComposeSession
    context = cls(API, ca_bundle=good)._verify
    assert isinstance(context, ssl.SSLContext)
    system = ssl.create_default_context()
    assert set(system.get_ca_certs(binary_form=True)) < set(context.get_ca_certs(binary_form=True))
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert cls(API)._verify is True
    with pytest.raises(ConfigError, match="ca_bundle"):
        cls(API, ca_bundle=bad)


@pytest.mark.asyncio
async def test_redirect_is_refused(session_kind: str, fake_tenant: FakeTenant) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    transport = _mock(lambda _: httpx.Response(302, headers={"Location": "https://elsewhere.test/auth/me"}))
    async with stored_api(settings, fake_tenant, transport, store, session_kind) as api:
        with pytest.raises(ProtocolError, match="redirect"):
            await invoke(api, "whoami")
    assert len(transport.requests) == 1
    assert fake_tenant.requests == []


@pytest.mark.asyncio
async def test_environment_proxy_and_netrc_are_ignored(
    session_kind: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_compose_api: FakeComposeApi,
) -> None:
    netrc = tmp_path / "netrc"
    netrc.write_text("machine api.compose.test login unexpected password secret\n")
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:9999")
    api: Session = (
        ComposeSession(API, transport=SyncOverAsyncTransport(fake_compose_api.transport))
        if session_kind == "sync"
        else AsyncComposeSession(API, transport=fake_compose_api.transport)
    )
    try:
        await invoke(api, "simulators")
        client = (
            api.client.get_httpx_client() if isinstance(api, ComposeSession) else api.client.get_async_httpx_client()
        )
        assert client.trust_env is False
    finally:
        await invoke(api, "close" if session_kind == "sync" else "aclose")
    [request] = fake_compose_api.transport.requests
    assert str(request.url) == API + "/core/simulator/list"
    assert "authorization" not in request.headers


SUBMISSIONS: list[tuple[str, str, tuple[Any, ...], dict[str, Any]]] = [
    ("submit", "/simulation/run", (b"archive",), {}),
    ("submit_copasi", "/curated/copasi", (b"sbml",), {"start": 0, "duration": 1, "points": 2}),
    ("submit_tellurium", "/curated/tellurium", (b"sbml",), {"start": 0, "end": 1, "points": 2}),
    ("sedml_run", "/sedml/run", (b"archive",), {}),
    ("run_biomodel", "/sources/biomodels/{model_id}/run", ("BIOMD1",), {}),
    ("run_biosimulations_project", "/sources/biosimulations/{project_id}/run", ("project",), {}),
    ("run_suite", "/suites/{name}/run", ("suite",), {"environment_versions": ["default"]}),
    ("verify_comparison", "/comparisons/{comparison_id}/verify", (354,), {}),
    ("verify_suite_run", "/suites/{name}/runs/{number}/verify", ("suite", 1), {}),
    (
        "mark_suite_problem",
        "/suites/{name}/problems",
        ("suite", "biomodels:BIOMD0000000039"),
        {"category": "NONINTEGER_STOICH", "reason": "0.25 for CaER"},
    ),
    ("build_environment", "/registry/environments/{name}/build", ("environment",), {}),
    ("build_simulator", "/registry/simulators/{simulator_id}/build", (7,), {}),
    ("create_environment_version", "/registry/environments/{name}/versions", ("environment",), {}),
    (
        "run_environment_compliance",
        "/registry/environments/{name}/versions/{number}/compliance",
        ("environment", 1),
        {},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "args", "kwargs"), SUBMISSIONS, ids=[s[0] for s in SUBMISSIONS])
@pytest.mark.parametrize("failure", ["401", "connect", "timeout", "500", "unreadable"])
async def test_all_submissions_are_sent_exactly_once(
    session_kind: str,
    fake_tenant: FakeTenant,
    method: str,
    path: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    failure: str,
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    _renewal(fake_tenant)

    def answer(_: httpx.Request) -> httpx.Response:
        if failure == "connect":
            raise httpx.ConnectError("refused")
        if failure == "timeout":
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200 if failure == "unreadable" else int(failure), text="{")

    transport = _mock(answer)
    expected = AuthError if failure == "401" else NetworkError if failure == "connect" else UncertainOutcomeError
    async with stored_api(settings, fake_tenant, transport, store, session_kind) as api:
        with pytest.raises(expected) as caught:
            await invoke(api, method, *args, **kwargs)
    [request] = transport.requests
    assert request.method == "POST"
    values = iter(args)
    expected_path = re.sub(r"\{[^}]+\}", lambda _: str(next(values)), path)
    assert request.url.path == expected_path
    if failure == "401":
        assert "was not submitted" in str(caught.value)
        assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 1
    elif failure == "connect":
        assert "known not sent" in str(caught.value)
    else:
        assert isinstance(caught.value, UncertainOutcomeError)
        assert caught.value.category == "uncertain"
    if failure != "401":
        assert fake_tenant.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("submission", [False, True])
async def test_environment_rejection_never_even_attempts_renewal(
    session_kind: str,
    submission: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = EnvironmentToken("rejected-environment-token")
    transport = _mock(lambda _: httpx.Response(401))

    def forbidden_renewal(*_: Any) -> None:
        pytest.fail("environment tokens cannot be renewed")

    api: Session
    if session_kind == "sync":
        monkeypatch.setattr(env, "renew", forbidden_renewal)
        api = ComposeSession(API, tokens=env, transport=SyncOverAsyncTransport(transport))
    else:
        source = env.as_async()
        monkeypatch.setattr(source, "renew", forbidden_renewal)
        api = AsyncComposeSession(API, tokens=source, transport=transport)
    try:
        with pytest.raises(AuthError, match="COMPOSE_API_TOKEN") as caught:
            if submission:
                await invoke(api, "submit", b"archive")
            else:
                await invoke(api, "simulators")
        if submission:
            assert "submission was not sent" in str(caught.value)
    finally:
        await invoke(api, "close" if session_kind == "sync" else "aclose")
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_renewed_requests_keep_the_destination_guard(
    session_kind: str,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
) -> None:
    from compose_api_client.api.compute import get_simulator_list

    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store, access=REJECTED)
    _renewal(fake_tenant)
    attempts = 0
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store, session_kind) as api:
        if isinstance(api, AsyncComposeSession):

            async def send_async(client: Any) -> Any:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    return await get_simulator_list.asyncio_detailed(client=client)
                return await client.get_async_httpx_client().get("https://api.compose.test.evil.example/auth/me")

            with pytest.raises(ProtocolError, match="refused to send credentials"):
                await api._send(CURRENT_PRINCIPAL, send_async)
        else:

            def send_sync(client: Any) -> Any:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    return get_simulator_list.sync_detailed(client=client)
                return client.get_httpx_client().get("https://api.compose.test.evil.example/auth/me")

            with pytest.raises(ProtocolError, match="refused to send credentials"):
                await asyncio.to_thread(api._send, CURRENT_PRINCIPAL, send_sync)
    assert attempts == 2
    assert fake_compose_api.transport.paths() == ["/core/simulator/list"]
    assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 1
