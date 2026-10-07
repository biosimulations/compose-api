"""The API boundary: the generated client against the real app over ASGI, carrying real signed tokens."""

import asyncio
import io
import json
import zipfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from compose_api.api.client.models import JobStatus
from compose_api.api.main import app
from compose_api.authentication import Auth0Verifier, JwksCache, get_auth0_verifier
from compose_api.cli.api import (
    CURRENT_PRINCIPAL,
    ComposeApi,
    OneCommandSession,
    StoredSession,
    TokenSource,
    UnsafeRequestError,
)
from compose_api.cli.auth.oauth import Auth0OAuthClient
from compose_api.cli.auth.session import AuthSession
from compose_api.cli.auth.storage import MemoryCredentialStore
from compose_api.cli.commands.common import Wiring
from compose_api.cli.config import CliSettings
from compose_api.cli.errors import (
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
)
from compose_api.cli.main import main
from tests.fixtures.auth_fixtures import AUTH0_TEST_DOMAIN, AUTH0_TEST_ISSUER, FakeAuth0
from tests.fixtures.cli_fixtures import (
    DESCRIPTION_CANARY,
    REFRESH_TOKEN,
    FakeBrowser,
    FakeComposeApi,
    FakeTenant,
    RecordingTransport,
    cli_settings,
    seed_session,
    use_profile,
    wire,
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


@asynccontextmanager
async def stored_api(
    settings: CliSettings, tenant: FakeTenant, transport: httpx.AsyncBaseTransport, store: MemoryCredentialStore
) -> AsyncIterator[ComposeApi]:
    async with Auth0OAuthClient(settings, transport=tenant.transport) as oauth:
        yield ComposeApi(settings, StoredSession(AuthSession(settings, store), oauth), transport=transport)


def _mock(handler: Callable[[httpx.Request], httpx.Response]) -> RecordingTransport:
    return RecordingTransport(httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_the_api_verifies_the_session_with_real_signed_tokens(
    fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    record = await seed_session(settings, fake_tenant, store)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store) as api:
        _, principal = await api.verify_identity()

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
    fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    archive = _archive()
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store) as api:
        simulators = await api.list_simulators()
        run = await api.simulation_status(FakeComposeApi.SIMULATION_ID)
        experiment = await api.submit_simulation(
            io.BytesIO(archive), file_name="experiment.omex", interval_time=2.5, batch=True
        )
        await api.submit_simulation(io.BytesIO(archive), file_name="second.omex", interval_time=None, batch=False)

    [version] = simulators.versions
    assert (version.database_id, version.container_def_hash) == (7, "0123456789abcdef0123456789abcdef")
    assert (run.sim_id, run.status) == (FakeComposeApi.SIMULATION_ID, JobStatus.RUNNING)
    assert experiment.simulation_database_id == FakeComposeApi.SIMULATION_ID
    # The generated multipart encoding, parsed by the real route: every byte, the name and both query parameters.
    assert fake_compose_api.uploads == [
        {"file_name": "experiment.omex", "content": archive, "batch": True, "interval_time": 2.5},
        {"file_name": "second.omex", "content": archive, "batch": False, "interval_time": 1.0},
    ]
    assert fake_compose_api.created == 2


@pytest.mark.asyncio
async def test_an_unknown_simulation_is_not_found_not_pending(
    fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store) as api:
        with pytest.raises(NotFoundError, match="there is no simulation 999 on this server") as caught:
            await api.simulation_status(999)
    assert DESCRIPTION_CANARY not in caught.value.message


@pytest.mark.asyncio
async def test_a_rejected_read_is_renewed_once_and_replayed_once(
    fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    first = await seed_session(settings, fake_tenant, store, access=REJECTED)
    _renewal(fake_tenant)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store) as api:
        simulators = await api.list_simulators()

    assert simulators.versions
    assert fake_compose_api.transport.paths() == ["/core/simulator/list"] * 2
    assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 1
    renewed = store.load(settings.binding_key(persistent=True))
    assert renewed is not None and renewed.generation == first.generation + 1
    assert fake_compose_api.transport.closed == 2, "each attempt closes its own client"
    for request in fake_tenant.requests:
        assert "authorization" not in request.headers, "the bearer never goes to Auth0"


@pytest.mark.asyncio
async def test_a_second_rejection_is_final_and_points_at_the_profile(
    fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi, fake_auth0: FakeAuth0
) -> None:
    jwks = JwksCache(f"{AUTH0_TEST_ISSUER}.well-known/jwks.json", transport=httpx.MockTransport(fake_auth0.handle_jwks))
    elsewhere = Auth0Verifier(domain=AUTH0_TEST_DOMAIN, audience="https://elsewhere.test", jwks=jwks)
    app.dependency_overrides[get_auth0_verifier] = lambda: elsewhere
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    _renewal(fake_tenant)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store) as api:
        with pytest.raises(AuthError, match=r"even after renewing the session.*auth0_audience"):
            await api.list_simulators()
    assert fake_compose_api.transport.paths() == ["/core/simulator/list"] * 2
    assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 1


@pytest.mark.asyncio
async def test_a_one_command_session_cannot_be_renewed(
    fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    record = await seed_session(settings, fake_tenant, store, access=REJECTED)
    api = ComposeApi(settings, OneCommandSession(record), transport=fake_compose_api.transport)
    with pytest.raises(AuthError, match="cannot be renewed"):
        await api.list_simulators()
    assert fake_compose_api.transport.paths() == ["/core/simulator/list"]


@pytest.mark.asyncio
async def test_a_rejected_submission_is_never_replayed(
    fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    first = await seed_session(settings, fake_tenant, store, access=REJECTED)
    _renewal(fake_tenant)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store) as api:
        with pytest.raises(AuthError, match="was not submitted; the session was renewed, so run the command again"):
            await api.submit_simulation(io.BytesIO(_archive()), file_name="x.omex", interval_time=None, batch=False)
    assert fake_compose_api.transport.paths() == ["/simulation/run"]
    assert fake_compose_api.created == 0
    renewed = store.load(settings.binding_key(persistent=True))
    assert renewed is not None and renewed.generation == first.generation + 1, "ready for the next invocation"


@pytest.mark.asyncio
async def test_forbidden_is_final_and_never_renews(fake_tenant: FakeTenant) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    transport = _mock(lambda _request: httpx.Response(403, json={"detail": DESCRIPTION_CANARY}))
    async with stored_api(settings, fake_tenant, transport, store) as api:
        with pytest.raises(ForbiddenError, match="signing in again will not change that") as caught:
            await api.list_simulators()
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
    ("submit-500", "submit", httpx.Response(500), ServerError, "may or may not have been created"),
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
    ("submit-unreadable", "submit", httpx.Response(200, text="{"), ProtocolError, "may or may not have been created"),
]


async def _operation(api: ComposeApi, name: str) -> object:
    if name == "list":
        return await api.list_simulators()
    if name == "status":
        return await api.simulation_status(5)
    return await api.submit_simulation(io.BytesIO(_archive()), file_name="x.omex", interval_time=None, batch=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "response", "error", "fragment"),
    [case[1:] for case in FAILURES],
    ids=[case[0] for case in FAILURES],
)
async def test_every_status_is_interpreted_before_a_body_is_trusted(
    fake_tenant: FakeTenant, operation: str, response: httpx.Response, error: type[Exception], fragment: str
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    transport = _mock(lambda _request: response)
    async with stored_api(settings, fake_tenant, transport, store) as api:
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
    fake_tenant: FakeTenant, operation: str, failure: httpx.HTTPError, fragment: str, unknown_outcome: bool
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)

    def broken(_request: httpx.Request) -> httpx.Response:
        raise failure

    transport = _mock(broken)
    async with stored_api(settings, fake_tenant, transport, store) as api:
        with pytest.raises(NetworkError, match=fragment) as caught:
            await _operation(api, operation)
    assert ("may or may not have been created" in caught.value.message) is unknown_outcome
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_a_session_about_to_expire_is_renewed_before_the_request(
    fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi
) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store, expires_in=30)
    _renewal(fake_tenant)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store) as api:
        await api.verify_identity()
        await api.list_simulators()
    assert fake_compose_api.transport.paths() == ["/auth/me", "/core/simulator/list"], "no 401 round trip"
    assert len(fake_tenant.forms(FakeTenant.TOKEN)) == 1
    stored = store.load(settings.binding_key(persistent=True))
    assert stored is not None and stored.api_verified_at is not None


@pytest.mark.asyncio
async def test_a_confirmation_survives_renewal(fake_tenant: FakeTenant, fake_compose_api: FakeComposeApi) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    async with stored_api(settings, fake_tenant, fake_compose_api.transport, store) as api:
        await api.verify_identity()
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
async def test_an_api_that_names_someone_else_is_not_believed(fake_tenant: FakeTenant) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    await seed_session(settings, fake_tenant, store)
    principal = {
        "issuer": AUTH0_TEST_ISSUER,
        "subject": "auth0|someone-else",
        "audience": [],
        "roles": ["user"],
        "scopes": [],
        "permissions": [],
    }
    transport = _mock(lambda _request: httpx.Response(200, json=principal))
    async with stored_api(settings, fake_tenant, transport, store) as api:
        with pytest.raises(ProtocolError, match="different user"):
            await api.verify_identity()
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
        "https://api.compose.test/results/simulation/results",
        "https://api.compose.test/",
    ],
)
async def test_credentials_go_only_to_this_profiles_api_operations(fake_tenant: FakeTenant, url: str) -> None:
    settings, store = _settings(), MemoryCredentialStore()
    record = await seed_session(settings, fake_tenant, store)
    transport = _mock(lambda _request: httpx.Response(200))
    api = ComposeApi(settings, OneCommandSession(record), transport=transport)
    await api._guard(httpx.Request("GET", f"{API}/auth/me"))  # the configured origin and an allowed path

    with pytest.raises(UnsafeRequestError):
        await api._guard(httpx.Request("GET", url))

    async def wander(client: Any) -> Any:
        return await client.get_async_httpx_client().get(url)

    with pytest.raises(ProtocolError, match="refused to send credentials"):
        await api._attempt(CURRENT_PRINCIPAL, record, wander)
    assert transport.requests == [], "the request never left"


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


def test_a_ca_bundle_extends_tls_trust_and_a_bad_one_is_a_configuration_error(tmp_path: Path) -> None:
    good, bad = tmp_path / "ca.pem", tmp_path / "bad.pem"
    _self_signed_certificate(good)
    bad.write_text("not a certificate")
    unused = cast(TokenSource, None)  # building the client contacts nothing and reads no session
    assert ComposeApi(_settings(ca_bundle=str(good)), unused)._verify is not True
    assert ComposeApi(_settings(), unused)._verify is True
    with pytest.raises(ConfigError, match="ca_bundle"):
        ComposeApi(_settings(ca_bundle=str(bad)), unused)


# Commands, end to end through main().


@pytest.fixture
def stored(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
) -> MemoryCredentialStore:
    """A signed-in profile whose commands reach the fake tenant and the real app over ASGI."""
    settings = _settings()
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
    return store


def test_simulators_list_text_and_json(stored: MemoryCredentialStore, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["simulators", "list"]) == ExitCode.OK
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["ID", "DEFINITION", "PACKAGES", "REGISTERED"]
    assert lines[1].split()[:3] == ["7", "0123456789ab", "0"]
    assert main(["simulators", "list", "--json"]) == ExitCode.OK
    document = json.loads(capsys.readouterr().out)
    assert [version["database_id"] for version in document["versions"]] == [7]


def test_simulation_status_and_not_found(stored: MemoryCredentialStore, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["simulations", "status", str(FakeComposeApi.SIMULATION_ID)]) == ExitCode.OK
    assert capsys.readouterr().out.startswith(f"Simulation {FakeComposeApi.SIMULATION_ID}: running")
    assert main(["simulations", "status", "999", "--json"]) == ExitCode.FAILURE
    error = json.loads(capsys.readouterr().out)["error"]
    assert error == {
        "category": "not_found",
        "message": "there is no simulation 999 on this server",
        "exit_code": 1,
    }


def test_submit_uploads_the_archive_once_and_reports_a_reference(
    stored: MemoryCredentialStore,
    fake_compose_api: FakeComposeApi,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = tmp_path / "experiment.omex"
    archive.write_bytes(_archive())
    argv = ["simulations", "submit", str(archive), "--interval-time", "2.5", "--batch"]
    assert main(argv) == ExitCode.OK
    out = capsys.readouterr().out
    assert f"Submitted simulation {FakeComposeApi.SIMULATION_ID}" in out
    assert f"compose-api simulations status {FakeComposeApi.SIMULATION_ID}" in out
    assert "complete" not in out.lower(), "a submission is a reference, not a result"
    assert main([*argv, "--json"]) == ExitCode.OK
    assert json.loads(capsys.readouterr().out)["simulation_database_id"] == FakeComposeApi.SIMULATION_ID
    assert [upload["content"] for upload in fake_compose_api.uploads] == [archive.read_bytes()] * 2


@pytest.mark.parametrize("contents", [None, b"", b"not a zip archive"], ids=["missing", "empty", "not-zip"])
def test_submit_checks_the_archive_before_anything_else(
    stored: MemoryCredentialStore,
    fake_compose_api: FakeComposeApi,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    contents: bytes | None,
) -> None:
    archive = tmp_path / "experiment.omex"
    if contents is not None:
        archive.write_bytes(contents)
    assert main(["simulations", "submit", str(archive), "--json"]) == ExitCode.USAGE
    assert json.loads(capsys.readouterr().out)["error"]["category"] == "usage"
    assert fake_compose_api.transport.requests == []


@pytest.mark.parametrize(
    "argv",
    [["simulators", "list"], ["simulations", "status", "41"], ["simulations", "submit", "{archive}"]],
)
def test_without_a_session_api_commands_never_sign_in_on_their_own(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_network_or_browser: list[str],
    argv: list[str],
) -> None:
    archive = tmp_path / "experiment.omex"
    archive.write_bytes(_archive())
    use_profile(monkeypatch, _settings())
    api = _mock(lambda _request: httpx.Response(200))
    browser = FakeBrowser(FakeTenant(FakeAuth0()))
    wire(
        monkeypatch,
        Wiring(store_factory=lambda _settings: MemoryCredentialStore(), launcher=browser, api_transport=api),
    )
    assert main([part.format(archive=archive) for part in argv]) == ExitCode.AUTH_REQUIRED
    assert "No session for this profile; sign in first" in capsys.readouterr().err
    assert browser.urls == [] and api.requests == []


@pytest.mark.parametrize("device", [False, True], ids=["browser", "device"])
def test_ephemeral_auth_signs_in_for_one_command_and_keeps_nothing(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
    device: bool,
) -> None:
    use_profile(monkeypatch, cli_settings())

    def no_store(_settings: CliSettings) -> MemoryCredentialStore:
        raise AssertionError("--ephemeral-auth never opens the persistent store")

    if device:
        fake_tenant.queue(FakeTenant.DEVICE, fake_tenant.device_response(interval=1))
        fake_tenant.queue(FakeTenant.TOKEN, fake_tenant.token_response())
    wire(
        monkeypatch,
        Wiring(
            store_factory=no_store,
            launcher=FakeBrowser(fake_tenant),
            auth0_transport=fake_tenant.transport,
            api_transport=fake_compose_api.transport,
        ),
    )
    argv = ["simulators", "list", "--ephemeral-auth", "--json", *(["--device"] if device else [])]
    assert main(argv) == ExitCode.OK
    assert json.loads(capsys.readouterr().out)["versions"][0]["database_id"] == FakeComposeApi.SIMULATOR_ID
    [request] = fake_compose_api.transport.requests
    assert request.headers["authorization"].startswith("Bearer ey")
    scope = (fake_tenant.forms(FakeTenant.DEVICE)[0] if device else fake_tenant.authorize_requests[0])["scope"]
    assert "offline_access" not in scope


def test_login_is_confirmed_by_the_api(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = cli_settings()
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: store,
            launcher=FakeBrowser(fake_tenant),
            auth0_transport=fake_tenant.transport,
            api_transport=fake_compose_api.transport,
        ),
    )
    assert main(["auth", "login"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert f"Identity: {fake_tenant.subject} ({AUTH0_TEST_ISSUER})" in out
    assert "API: confirmed this identity just now" in out
    assert fake_compose_api.transport.paths() == ["/auth/me"]
    record = store.load(settings.binding_key(persistent=True))
    assert record is not None and record.api_verified_at is not None and record.refresh_token is not None
    assert record.refresh_token.get_secret_value() == REFRESH_TOKEN


def test_an_unreachable_api_after_login_keeps_the_session_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = cli_settings()
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()

    def unreachable(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: store,
            launcher=FakeBrowser(fake_tenant),
            auth0_transport=fake_tenant.transport,
            api_transport=httpx.MockTransport(unreachable),
        ),
    )
    assert main(["auth", "login", "--json"]) == ExitCode.NETWORK
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["category"] == "network"
    assert error["message"].startswith("signed in and saved the session, but the Compose API did not confirm it")
    assert "auth status --verify" in error["message"]
    record = store.load(settings.binding_key(persistent=True))
    assert record is not None and record.api_verified_at is None


def test_status_is_local_until_asked_to_verify(
    stored: MemoryCredentialStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["auth", "status"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "API: never confirmed" in out
    assert main(["auth", "status", "--verify", "--json"]) == ExitCode.OK
    document = json.loads(capsys.readouterr().out)
    assert document["checked_with_api"] is True and document["api_verified_at"] is not None
    assert main(["auth", "status"]) == ExitCode.OK
    assert "API: last confirmed" in capsys.readouterr().out
    assert main(["auth", "status", "--json"]) == ExitCode.OK
    assert json.loads(capsys.readouterr().out)["checked_with_api"] is False


def test_a_failed_verification_is_not_a_sign_out(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings()
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    before = asyncio.run(seed_session(settings, fake_tenant, store))

    def unreachable(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: store,
            auth0_transport=fake_tenant.transport,
            api_transport=httpx.MockTransport(unreachable),
        ),
    )
    assert main(["auth", "status", "--verify"]) == ExitCode.NETWORK
    assert "This is not a sign-out" in capsys.readouterr().err
    assert store.load(settings.binding_key(persistent=True)) == before


def test_verify_without_a_session_contacts_nothing(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_network_or_browser: list[str],
) -> None:
    use_profile(monkeypatch, _settings())
    api = _mock(lambda _request: httpx.Response(200))
    wire(monkeypatch, Wiring(store_factory=lambda _settings: MemoryCredentialStore(), api_transport=api))
    assert main(["auth", "status", "--verify"]) == ExitCode.AUTH_REQUIRED
    assert "No session" in capsys.readouterr().out
    assert api.requests == []
