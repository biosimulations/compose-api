import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from httpx import ASGITransport

from compose_api.api.main import app
from compose_api.authentication import (
    Auth0Verifier,
    AuthenticatedPrincipal,
    AuthenticationError,
    JwksCache,
    OptionalPrincipal,
    get_auth0_verifier,
    get_optional_principal,
)
from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseService
from tests.fixtures.auth_fixtures import AUTH0_TEST_AUDIENCE, AUTH0_TEST_DOMAIN, FakeAuth0

MALFORMED_HEADERS = ["Basic dXNlcjpwYXNz", "Bearer", "", "Bearer a b", "Bearer not-a-jwt", "Token abc"]

# -- verifier -- #


@pytest.mark.asyncio
async def test_valid_token_yields_principal(fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier) -> None:
    principal = await auth0_verifier.verify(fake_auth0.token())
    assert principal.subject == "auth0|test-user"
    assert AUTH0_TEST_AUDIENCE in principal.audience
    assert principal.scopes == {"openid", "profile"}
    assert principal.permissions == frozenset()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim_overrides", "category"),
    [
        ({"exp": int(time.time()) - 120}, "token_expired"),
        ({"iss": "https://someone-else.auth0.com/"}, "invalid_issuer"),
        ({"aud": "https://another-api"}, "invalid_audience"),
        ({"sub": None}, "missing_claim"),
    ],
)
async def test_invalid_claims_rejected(
    fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier, claim_overrides: dict[str, Any], category: str
) -> None:
    with pytest.raises(AuthenticationError) as excinfo:
        await auth0_verifier.verify(fake_auth0.token(**claim_overrides))
    assert excinfo.value.category == category


@pytest.mark.asyncio
async def test_wrong_signing_key_rejected(fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier) -> None:
    impostor = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(AuthenticationError) as excinfo:
        await auth0_verifier.verify(fake_auth0.token(signing_key=impostor))
    assert excinfo.value.category == "invalid_signature"


@pytest.mark.asyncio
async def test_symmetric_algorithm_rejected(auth0_verifier: Auth0Verifier) -> None:
    token = jwt.encode(
        {"sub": "x"}, "a-shared-secret-of-at-least-32-bytes", algorithm="HS256", headers={"kid": "key-1"}
    )
    with pytest.raises(AuthenticationError) as excinfo:
        await auth0_verifier.verify(token)
    assert excinfo.value.category == "unsupported_algorithm"


@pytest.mark.asyncio
async def test_jwks_is_cached_and_refreshed_on_rotation(fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier) -> None:
    await auth0_verifier.verify(fake_auth0.token())
    await auth0_verifier.verify(fake_auth0.token())
    assert fake_auth0.jwks_requests == 1

    fake_auth0.add_key("key-2")
    await auth0_verifier.verify(fake_auth0.token(kid="key-2"))
    assert fake_auth0.jwks_requests == 2

    unknown = jwt.encode({"sub": "x"}, fake_auth0.keys["key-1"], algorithm="RS256", headers={"kid": "retired"})
    with pytest.raises(AuthenticationError) as excinfo:
        await auth0_verifier.verify(unknown)
    assert excinfo.value.category == "unknown_kid"
    assert fake_auth0.jwks_requests == 3


@pytest.mark.asyncio
async def test_jwks_outage_fails_closed(fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier) -> None:
    fake_auth0.jwks_available = False
    with pytest.raises(AuthenticationError) as excinfo:
        await auth0_verifier.verify(fake_auth0.token())
    assert excinfo.value.category == "jwks_unavailable"


@pytest.mark.asyncio
async def test_jwks_timeout_fails_closed(fake_auth0: FakeAuth0) -> None:
    def time_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    jwks = JwksCache("https://unused/jwks", transport=httpx.MockTransport(time_out))
    verifier = Auth0Verifier(domain=AUTH0_TEST_DOMAIN, audience=AUTH0_TEST_AUDIENCE, jwks=jwks)
    with pytest.raises(AuthenticationError) as excinfo:
        await verifier.verify(fake_auth0.token())
    assert excinfo.value.category == "jwks_unavailable"


@pytest.mark.asyncio
async def test_cached_keys_survive_a_jwks_outage(fake_auth0: FakeAuth0) -> None:
    """Pinned policy: once keys are cached, a failed refresh keeps serving them rather than rejecting every token."""
    jwks = JwksCache(
        "https://unused/jwks",
        transport=httpx.MockTransport(fake_auth0.handle_jwks),
        ttl_seconds=0,  # every lookup is past its TTL, so every lookup attempts a refresh
        min_refresh_interval_seconds=0,
    )
    verifier = Auth0Verifier(domain=AUTH0_TEST_DOMAIN, audience=AUTH0_TEST_AUDIENCE, jwks=jwks)
    await verifier.verify(fake_auth0.token())
    fake_auth0.jwks_available = False
    principal = await verifier.verify(fake_auth0.token())
    assert principal.subject == "auth0|test-user"
    assert fake_auth0.jwks_requests == 2


@pytest.mark.asyncio
async def test_unknown_kids_cannot_force_repeated_refreshes(fake_auth0: FakeAuth0) -> None:
    """Pinned policy: at most one JWKS refresh per interval, however many unknown kids arrive."""
    jwks = JwksCache("https://unused/jwks", transport=httpx.MockTransport(fake_auth0.handle_jwks))
    verifier = Auth0Verifier(domain=AUTH0_TEST_DOMAIN, audience=AUTH0_TEST_AUDIENCE, jwks=jwks)
    await verifier.verify(fake_auth0.token())
    for kid in ("forged-1", "forged-2", "forged-3"):
        forged = jwt.encode({"sub": "x"}, fake_auth0.keys["key-1"], algorithm="RS256", headers={"kid": kid})
        with pytest.raises(AuthenticationError) as excinfo:
            await verifier.verify(forged)
        assert excinfo.value.category == "unknown_kid"
    assert fake_auth0.jwks_requests == 1


@pytest.mark.asyncio
async def test_missing_kid_rejected(fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier) -> None:
    token = jwt.encode({"sub": "x"}, fake_auth0.keys["key-1"], algorithm="RS256")
    with pytest.raises(AuthenticationError) as excinfo:
        await auth0_verifier.verify(token)
    assert excinfo.value.category == "missing_kid"


@pytest.mark.asyncio
async def test_permissions_claim_is_normalised(fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier) -> None:
    principal = await auth0_verifier.verify(fake_auth0.token(permissions=["run:simulations", 7], scope=None))
    assert principal.permissions == {"run:simulations"}
    assert principal.scopes == frozenset()


def test_verifier_follows_settings() -> None:
    with override_settings(auth0_domain="tenant.example.auth0.com", auth0_audience="https://api.example"):
        verifier = get_auth0_verifier()
        assert verifier is not None
        assert verifier.issuer == "https://tenant.example.auth0.com/"
        assert verifier.audience == "https://api.example"
    with override_settings(auth0_domain="tenant.example.auth0.com", auth0_audience=""):
        assert get_auth0_verifier() is None


# -- FastAPI dependency -- #


@pytest_asyncio.fixture
async def principal_client(auth0_verifier: Auth0Verifier) -> AsyncGenerator[httpx.AsyncClient]:
    """A throwaway app whose one route echoes the principal, so the dependency is tested apart from any handler."""
    probe = FastAPI()

    @probe.get("/whoami")
    async def whoami(principal: OptionalPrincipal) -> dict[str, str | None]:
        return {"subject": principal.subject if principal else None}

    probe.dependency_overrides[get_auth0_verifier] = lambda: auth0_verifier
    async with httpx.AsyncClient(transport=ASGITransport(app=probe), base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_no_header_is_anonymous(principal_client: httpx.AsyncClient) -> None:
    response = await principal_client.get("/whoami")
    assert response.status_code == 200
    assert response.json() == {"subject": None}


@pytest.mark.asyncio
async def test_valid_token_reaches_handler(principal_client: httpx.AsyncClient, fake_auth0: FakeAuth0) -> None:
    response = await principal_client.get("/whoami", headers={"Authorization": f"Bearer {fake_auth0.token()}"})
    assert response.status_code == 200
    assert response.json() == {"subject": "auth0|test-user"}


@pytest.mark.asyncio
@pytest.mark.parametrize("header", MALFORMED_HEADERS)
async def test_malformed_header_is_401_not_anonymous(principal_client: httpx.AsyncClient, header: str) -> None:
    response = await principal_client.get("/whoami", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid authentication credentials"}


@pytest.mark.asyncio
async def test_token_rejected_when_auth0_unconfigured(fake_auth0: FakeAuth0) -> None:
    probe = FastAPI()

    @probe.get("/whoami", dependencies=[Depends(get_optional_principal)])
    async def whoami() -> None:
        return None

    probe.dependency_overrides[get_auth0_verifier] = lambda: None
    async with httpx.AsyncClient(transport=ASGITransport(app=probe), base_url="http://testserver") as client:
        assert (await client.get("/whoami")).status_code == 200
        response = await client.get("/whoami", headers={"Authorization": f"Bearer {fake_auth0.token()}"})
        assert response.status_code == 401


# -- the real app -- #


@pytest_asyncio.fixture
async def app_with_test_auth0(auth0_verifier: Auth0Verifier) -> AsyncGenerator[None]:
    app.dependency_overrides[get_auth0_verifier] = lambda: auth0_verifier
    yield
    del app.dependency_overrides[get_auth0_verifier]


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
@pytest.mark.parametrize("header", MALFORMED_HEADERS)
async def test_every_router_rejects_bad_credentials(http_api_client: httpx.AsyncClient, header: str) -> None:
    for method, path in [
        ("GET", "/core/simulator/list"),
        ("GET", "/results/simulation/status?simulation_id=1"),
        ("POST", "/simulation/run"),
        ("POST", "/curated/copasi"),
    ]:
        response = await http_api_client.request(method, path, headers={"Authorization": header})
        assert response.status_code == 401, (method, path)


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"exp": int(time.time()) - 120},
        {"iss": "https://someone-else.auth0.com/"},
        {"aud": "https://another-api"},
    ],
)
async def test_real_app_rejects_invalid_tokens_without_leaking_them(
    http_api_client: httpx.AsyncClient,
    fake_auth0: FakeAuth0,
    caplog: pytest.LogCaptureFixture,
    claim_overrides: dict[str, Any],
) -> None:
    impostor = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in (fake_auth0.token(**claim_overrides), fake_auth0.token(signing_key=impostor)):
        response = await http_api_client.get("/core/simulator/list", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert token not in response.text
        assert token not in caplog.text


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
async def test_catalog_route_anonymous_and_authenticated(
    http_api_client: httpx.AsyncClient, database_service: DatabaseService, fake_auth0: FakeAuth0
) -> None:
    anonymous = await http_api_client.get("/core/simulator/list")
    assert anonymous.status_code == 200
    authenticated = await http_api_client.get(
        "/core/simulator/list", headers={"Authorization": f"Bearer {fake_auth0.token()}"}
    )
    assert authenticated.status_code == 200
    # `timestamp` is stamped per request; the catalog itself must not depend on who asked.
    assert authenticated.json()["versions"] == anonymous.json()["versions"]


@pytest.mark.asyncio
async def test_health_and_version_ignore_credentials(http_api_client: httpx.AsyncClient) -> None:
    for path in ("/health", "/version"):
        response = await http_api_client.get(path, headers={"Authorization": "Basic garbage"})
        assert response.status_code == 200, path


# -- OpenAPI -- #


def test_openapi_documents_optional_bearer() -> None:
    schema = app.openapi()
    assert schema["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Optional Auth0 access token for this API. Omit it to call anonymously.",
    }
    assert schema["security"] == [{}, {"BearerAuth": []}]
    operations = [op for path in schema["paths"].values() for op in path.values()]
    assert all("security" not in op for op in operations), "per-operation security retypes the generated client"


def test_pbest_operations_keep_their_paths() -> None:
    """pbest calls these operations by name through the generated client; moving one is a breaking change."""
    paths_by_operation_id = {
        op["operationId"]: path for path, methods in app.openapi()["paths"].items() for op in methods.values()
    }
    assert paths_by_operation_id["run-simulation"] == "/simulation/run"
    assert paths_by_operation_id["get-simulations-status-batch"] == "/results/simulations/status/batch"
    assert paths_by_operation_id["get-simulation-status"] == "/results/simulation/status"
    assert paths_by_operation_id["get-simulation-results-file"] == "/results/simulation/results/file"
    assert paths_by_operation_id["run-copasi"] == "/curated/copasi"
    assert paths_by_operation_id["get-simulator-list"] == "/core/simulator/list"


def test_principal_is_immutable() -> None:
    principal = AuthenticatedPrincipal("s", "i", ("a",), frozenset(), frozenset())
    with pytest.raises(AttributeError):
        principal.subject = "other"  # type: ignore[misc]
