import ast
import asyncio
import base64
import importlib
import inspect
import json
import time
import uuid
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
import pytest_asyncio
import yaml
from compose_api_client import AuthenticatedClient, Client
from compose_api_client.api.results import get_simulation_status
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, HTTPException
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import ASGITransport

from compose_api.api.main import APP_ROUTERS, app
from compose_api.authentication import (
    DEFAULT_ROLE,
    JWKS_MAX_STALE_SECONDS,
    JWKS_MIN_REFRESH_INTERVAL_SECONDS,
    JWT_LEEWAY_SECONDS,
    ROLES_CLAIM,
    Auth0Verifier,
    AuthenticatedPrincipal,
    AuthenticationError,
    JwksCache,
    OptionalPrincipal,
    describe_caller,
    get_auth0_verifier,
    get_optional_principal,
)
from compose_api.authorization import Caller
from compose_api.config import REPO_ROOT, override_settings
from compose_api.db.database_service import DatabaseService
from compose_api.simulation.models import JobType, SimulationRequest, SimulatorVersion, Visibility
from tests.fixtures.auth_fixtures import AUTH0_TEST_AUDIENCE, AUTH0_TEST_DOMAIN, FakeAuth0

MALFORMED_HEADERS = ["Basic dXNlcjpwYXNz", "Bearer", "", "Bearer a b", "Bearer not-a-jwt", "Token abc"]


def _unsigned_token(algorithm: str) -> str:
    """A JWT with no signature. PyJWT will not mint `alg=none`, so the header is assembled directly."""

    def segment(value: dict[str, str]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{segment({'alg': algorithm, 'typ': 'JWT'})}.{segment({'sub': 'x'})}."


# -- verifier -- #


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", ["auth0|test-user", "test-client@clients"])
async def test_valid_token_yields_principal(fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier, subject: str) -> None:
    principal = await auth0_verifier.verify(fake_auth0.token(sub=subject))
    assert principal.subject == subject
    assert AUTH0_TEST_AUDIENCE in principal.audience
    assert principal.scopes == {"openid", "profile"}
    assert principal.permissions == frozenset()
    assert principal.roles == {DEFAULT_ROLE}  # an M2M token carries no roles claim, yet still gets the default role


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
async def test_unsigned_algorithm_rejected_without_jwks_fetch(
    fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier
) -> None:
    with pytest.raises(AuthenticationError) as excinfo:
        await auth0_verifier.verify(_unsigned_token("none"))
    assert excinfo.value.category == "unsupported_algorithm"
    assert fake_auth0.jwks_requests == 0


@pytest.mark.asyncio
async def test_jwks_is_cached_and_refreshed_on_rotation(
    fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = time.monotonic()
    monkeypatch.setattr("compose_api.authentication.time.monotonic", lambda: clock)
    await auth0_verifier.verify(fake_auth0.token())
    await auth0_verifier.verify(fake_auth0.token())
    assert fake_auth0.jwks_requests == 1

    fake_auth0.add_key("key-2")
    clock += JWKS_MIN_REFRESH_INTERVAL_SECONDS + 1
    await auth0_verifier.verify(fake_auth0.token(kid="key-2"))
    assert fake_auth0.jwks_requests == 2

    clock += JWKS_MIN_REFRESH_INTERVAL_SECONDS + 1
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
@pytest.mark.parametrize("document", [[], "unexpected", 7, {"keys": []}, {"keys": [None]}])
async def test_malformed_jwks_fails_closed(fake_auth0: FakeAuth0, document: object) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=document))
    verifier = Auth0Verifier(
        domain=AUTH0_TEST_DOMAIN,
        audience=AUTH0_TEST_AUDIENCE,
        jwks=JwksCache("https://unused/jwks", transport=transport),
    )
    probe = FastAPI()

    @probe.get("/whoami")
    async def whoami(principal: OptionalPrincipal) -> None:
        pytest.fail("Malformed JWKS must not reach the handler")

    probe.dependency_overrides[get_auth0_verifier] = lambda: verifier
    async with httpx.AsyncClient(transport=ASGITransport(app=probe), base_url="http://testserver") as client:
        response = await client.get("/whoami", headers={"Authorization": f"Bearer {fake_auth0.token()}"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid authentication credentials"}


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{"kid": []}, {"use": "enc"}, {"alg": "RS512"}])
async def test_jwks_only_selects_rs256_signing_keys(fake_auth0: FakeAuth0, overrides: dict[str, Any]) -> None:
    key = jwt.algorithms.RSAAlgorithm.to_jwk(fake_auth0.keys["key-1"].public_key(), as_dict=True)
    document = {"keys": [{**key, "kid": "key-1", **overrides}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=document))
    verifier = Auth0Verifier(
        domain=AUTH0_TEST_DOMAIN,
        audience=AUTH0_TEST_AUDIENCE,
        jwks=JwksCache("https://unused/jwks", transport=transport),
    )
    with pytest.raises(AuthenticationError):
        await verifier.verify(fake_auth0.token())


@pytest.mark.asyncio
async def test_cached_keys_survive_a_jwks_outage(fake_auth0: FakeAuth0) -> None:
    """Pinned policy: once keys are cached, a failed refresh keeps serving them rather than rejecting every token."""
    jwks = JwksCache(
        "https://unused/jwks",
        transport=httpx.MockTransport(fake_auth0.handle_jwks),
        ttl_seconds=0,  # every lookup is past its TTL, so every lookup attempts a refresh
        min_refresh_interval_seconds=0,  # override to test the outage behavior without back-off
    )
    verifier = Auth0Verifier(domain=AUTH0_TEST_DOMAIN, audience=AUTH0_TEST_AUDIENCE, jwks=jwks)
    await verifier.verify(fake_auth0.token())
    fake_auth0.jwks_available = False
    principal = await verifier.verify(fake_auth0.token())
    assert principal.subject == "auth0|test-user"
    assert fake_auth0.jwks_requests == 2


@pytest.mark.asyncio
async def test_cached_keys_expire_during_a_prolonged_outage(
    fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = time.monotonic()
    monkeypatch.setattr("compose_api.authentication.time.monotonic", lambda: clock)
    await auth0_verifier.verify(fake_auth0.token())
    fake_auth0.jwks_available = False
    clock += JWKS_MAX_STALE_SECONDS - 1
    await auth0_verifier.verify(fake_auth0.token())
    clock += 2
    with pytest.raises(AuthenticationError, match="jwks_unavailable"):
        await auth0_verifier.verify(fake_auth0.token())
    fake_auth0.jwks_available = True
    clock += 31
    await auth0_verifier.verify(fake_auth0.token())


@pytest.mark.asyncio
async def test_rotated_key_waits_out_the_refresh_backoff(
    fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key added inside the back-off window is not fetched until that window has elapsed."""
    clock = time.monotonic()
    monkeypatch.setattr("compose_api.authentication.time.monotonic", lambda: clock)
    await auth0_verifier.verify(fake_auth0.token())
    fake_auth0.add_key("key-2")
    with pytest.raises(AuthenticationError, match="unknown_kid"):
        await auth0_verifier.verify(fake_auth0.token(kid="key-2"))
    assert fake_auth0.jwks_requests == 1

    clock += JWKS_MIN_REFRESH_INTERVAL_SECONDS + 1
    principal = await auth0_verifier.verify(fake_auth0.token(kid="key-2"))
    assert principal.subject == "auth0|test-user"
    assert fake_auth0.jwks_requests == 2


@pytest.mark.asyncio
async def test_each_unknown_kid_refreshes_once_then_is_rejected(
    fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One forged kid may refresh JWKS. The next forged kids in that window must not."""
    clock = time.monotonic()
    monkeypatch.setattr("compose_api.authentication.time.monotonic", lambda: clock)
    await auth0_verifier.verify(fake_auth0.token())
    clock += JWKS_MIN_REFRESH_INTERVAL_SECONDS + 1

    def forged(kid: str) -> str:
        return jwt.encode({"sub": "x"}, fake_auth0.keys["key-1"], algorithm="RS256", headers={"kid": kid})

    with pytest.raises(AuthenticationError, match="unknown_kid"):
        await auth0_verifier.verify(forged("forged-1"))
    assert fake_auth0.jwks_requests == 2

    with pytest.raises(AuthenticationError, match="unknown_kid"):
        await auth0_verifier.verify(forged("forged-2"))
    assert fake_auth0.jwks_requests == 2

    with pytest.raises(AuthenticationError, match="unknown_kid"):
        await auth0_verifier.verify(forged("forged-3"))
    assert fake_auth0.jwks_requests == 2


@pytest.mark.asyncio
async def test_concurrent_unknown_kid_requests_share_one_refresh(fake_auth0: FakeAuth0) -> None:
    async def slow_jwks(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)  # hold the refresh open so the other requests queue behind it
        return fake_auth0.handle_jwks(request)

    jwks = JwksCache(
        "https://unused/jwks",
        transport=httpx.MockTransport(slow_jwks),
        min_refresh_interval_seconds=0,  # this test is the in-flight coalesce, not the back-off
    )
    verifier = Auth0Verifier(domain=AUTH0_TEST_DOMAIN, audience=AUTH0_TEST_AUDIENCE, jwks=jwks)
    await verifier.verify(fake_auth0.token())
    fake_auth0.add_key("key-2")
    principals = await asyncio.gather(*(verifier.verify(fake_auth0.token(kid="key-2")) for _ in range(5)))
    assert {p.subject for p in principals} == {"auth0|test-user"}
    assert fake_auth0.jwks_requests == 2


@pytest.mark.asyncio
async def test_expired_cache_backs_off_during_an_outage(fake_auth0: FakeAuth0) -> None:
    """A known kid past its TTL is refetched at most once per back-off interval, so an outage cannot stall requests."""
    jwks = JwksCache("https://unused/jwks", transport=httpx.MockTransport(fake_auth0.handle_jwks), ttl_seconds=0)
    verifier = Auth0Verifier(domain=AUTH0_TEST_DOMAIN, audience=AUTH0_TEST_AUDIENCE, jwks=jwks)
    await verifier.verify(fake_auth0.token())
    fake_auth0.jwks_available = False
    for _ in range(3):
        await verifier.verify(fake_auth0.token())
    assert fake_auth0.jwks_requests == 1


@pytest.mark.asyncio
async def test_cold_outage_inside_backoff_is_reported_as_unavailable(
    fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier
) -> None:
    """With no keys ever fetched, a request inside the back-off is an outage, not an unknown kid."""
    fake_auth0.jwks_available = False
    for _ in range(2):
        with pytest.raises(AuthenticationError, match="jwks_unavailable"):
            await auth0_verifier.verify(fake_auth0.token())
    assert fake_auth0.jwks_requests == 1


@pytest.mark.asyncio
async def test_cached_keys_survive_a_jwks_with_no_usable_keys(fake_auth0: FakeAuth0) -> None:
    """A fetch that succeeds but holds no RS256 signing key is handled like a failed fetch: the cache is kept."""
    unusable = False

    def jwks(request: httpx.Request) -> httpx.Response:
        response = fake_auth0.handle_jwks(request)
        if not unusable:
            return response
        return httpx.Response(200, json={"keys": [{**key, "use": "enc"} for key in response.json()["keys"]]})

    cache = JwksCache(
        "https://unused/jwks",
        transport=httpx.MockTransport(jwks),
        ttl_seconds=0,  # every lookup is past its TTL, so every lookup attempts a refresh
        min_refresh_interval_seconds=0,
    )
    verifier = Auth0Verifier(domain=AUTH0_TEST_DOMAIN, audience=AUTH0_TEST_AUDIENCE, jwks=cache)
    await verifier.verify(fake_auth0.token())
    unusable = True
    principal = await verifier.verify(fake_auth0.token())
    assert principal.subject == "auth0|test-user"
    assert fake_auth0.jwks_requests == 2
    await verifier.aclose()


@pytest.mark.asyncio
async def test_small_clock_skew_is_tolerated(fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier) -> None:
    """Auth0's clock a few seconds ahead of ours must not reject a token it has just issued."""
    now = int(time.time())
    principal = await auth0_verifier.verify(fake_auth0.token(iat=now + 5, exp=now + 300))
    assert principal.subject == "auth0|test-user"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"iat": int(time.time()) + JWT_LEEWAY_SECONDS + 60},
        {"exp": int(time.time()) - JWT_LEEWAY_SECONDS - 60},
    ],
    ids=["issued-in-the-future", "expired"],
)
async def test_skew_beyond_leeway_is_rejected(
    fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier, claim_overrides: dict[str, Any]
) -> None:
    with pytest.raises(AuthenticationError):
        await auth0_verifier.verify(fake_auth0.token(**claim_overrides))


@pytest.mark.asyncio
@pytest.mark.parametrize("nbf_offset", [0, JWT_LEEWAY_SECONDS // 2], ids=["now", "inside-leeway"])
async def test_nbf_inside_leeway_is_accepted(
    fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier, nbf_offset: int
) -> None:
    now = int(time.time())
    principal = await auth0_verifier.verify(fake_auth0.token(nbf=now + nbf_offset, exp=now + 300))
    assert principal.subject == "auth0|test-user"


@pytest.mark.asyncio
async def test_nbf_beyond_leeway_is_rejected(fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier) -> None:
    now = int(time.time())
    with pytest.raises(AuthenticationError) as excinfo:
        await auth0_verifier.verify(fake_auth0.token(nbf=now + JWT_LEEWAY_SECONDS + 60, exp=now + 300))
    assert excinfo.value.category == "invalid_token"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("roles_claim", "expected"),
    [
        (["admin", "publisher"], {"user", "admin", "publisher"}),
        (["user"], {"user"}),
        (["admin", 7, None, {"x": 1}], {"user", "admin"}),
        ("admin", {"user"}),
        ([], {"user"}),
    ],
    ids=["extra-roles", "user-listed-again", "non-strings-dropped", "not-a-list", "empty"],
)
async def test_roles_claim_adds_to_the_default_role(
    fake_auth0: FakeAuth0, auth0_verifier: Auth0Verifier, roles_claim: object, expected: set[str]
) -> None:
    claim: dict[str, Any] = {ROLES_CLAIM: roles_claim}  # a URL is not a valid keyword, so pass it via a dict
    principal = await auth0_verifier.verify(fake_auth0.token(**claim))
    assert principal.roles == expected


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
    async def whoami(principal: OptionalPrincipal) -> dict[str, str | list[str] | None]:
        return {
            "subject": principal.subject if principal else None,
            "roles": sorted(principal.roles) if principal else None,
        }

    probe.dependency_overrides[get_auth0_verifier] = lambda: auth0_verifier
    async with httpx.AsyncClient(transport=ASGITransport(app=probe), base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_no_header_is_anonymous(principal_client: httpx.AsyncClient) -> None:
    response = await principal_client.get("/whoami")
    assert response.status_code == 200
    assert response.json() == {"subject": None, "roles": None}  # anonymous: no role


@pytest.mark.asyncio
async def test_valid_token_reaches_handler(principal_client: httpx.AsyncClient, fake_auth0: FakeAuth0) -> None:
    response = await principal_client.get("/whoami", headers={"Authorization": f"Bearer {fake_auth0.token()}"})
    assert response.status_code == 200
    assert response.json() == {"subject": "auth0|test-user", "roles": ["user"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("header", MALFORMED_HEADERS)
async def test_malformed_header_is_401_not_anonymous(principal_client: httpx.AsyncClient, header: str) -> None:
    response = await principal_client.get("/whoami", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid authentication credentials"}


@pytest.mark.asyncio
async def test_multiple_authorization_headers_are_401(principal_client: httpx.AsyncClient) -> None:
    response = await principal_client.get(
        "/whoami",
        headers=[("Authorization", "Bearer one"), ("Authorization", "Bearer two")],
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid authentication credentials"}


@pytest.mark.asyncio
async def test_lowercase_bearer_scheme_is_accepted(principal_client: httpx.AsyncClient, fake_auth0: FakeAuth0) -> None:
    response = await principal_client.get("/whoami", headers={"Authorization": f"bearer {fake_auth0.token()}"})
    assert response.status_code == 200
    assert response.json()["subject"] == "auth0|test-user"


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
    # At least one route per router, and every route that reads through the authorization seam: the 401 must come
    # from the router-level dependency, before any lookup that could answer 404 instead.
    for method, path in [
        ("GET", "/core/simulator/list"),
        ("GET", "/auth/me"),
        ("GET", "/results/simulation/status?simulation_id=1"),
        ("GET", "/results/simulations/status/batch"),
        ("GET", "/results/simulation/results/file?simulation_id=1"),
        ("GET", "/results/simulation/events?simulation_id=1"),
        ("GET", "/results/simulation/trace?simulation_id=1"),
        ("GET", "/results/simulation/trace/chrome?simulation_id=1"),
        ("GET", "/results/simulator/build/status?simulator_id=1"),
        ("POST", "/simulation/run"),
        ("POST", "/curated/copasi"),
        ("GET", "/simulations"),
        ("GET", "/simulations/1"),
        ("GET", "/datasets"),
        ("GET", f"/datasets/{uuid.uuid4()}"),
        ("GET", f"/datasets/{uuid.uuid4()}/content"),
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
    caplog: "pytest.LogCaptureFixture",
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


# Every registered router is a business router; /health and /version live on the app itself.
BUSINESS_ROUTERS = APP_ROUTERS


def _reaches(dependant: Dependant, target: Callable[..., Any]) -> bool:
    return any(d.call is target or _reaches(d, target) for d in dependant.dependencies)


@pytest.mark.parametrize("router_name", BUSINESS_ROUTERS)
def test_every_active_handler_receives_the_caller_identity(router_name: str) -> None:
    """Router-level validation alone discards the principal. Each handler must also reach it through a parameter of
    its own: directly (`principal: OptionalPrincipal`), or through the authorization seam (`caller: OptionalCaller`,
    `ReadableSimulation`), whose get_caller depends on get_optional_principal. Reaching get_caller is not enough on its
    own: the chain has to end at the verified principal."""
    config = importlib.import_module(f"compose_api.api.routers.{router_name}").config
    assert [d.dependency for d in config.dependencies or []] == [get_optional_principal]
    routes = [route for route in config.router.routes if isinstance(route, APIRoute)]
    assert routes
    for route in routes:
        # Named dependencies are the handler's parameters; unnamed ones come from `dependencies=[...]` on the route.
        parameters = [d for d in route.dependant.dependencies if d.name is not None]
        assert any(d.call is get_optional_principal or _reaches(d, get_optional_principal) for d in parameters), (
            route.path
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
async def test_active_handler_sees_the_verified_principal(
    http_api_client: httpx.AsyncClient,
    fake_auth0: FakeAuth0,
    caplog: "pytest.LogCaptureFixture",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    async def stop_here(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPException(status_code=418)  # the handler got this far, so skip the real SBML parse and SLURM

    monkeypatch.setattr("compose_api.api.routers.curated.get_simulation_request_from_uploaded_file", stop_here)
    params = {"start_time": 0, "duration": 10, "num_data_points": 5}
    files = {"sbml": ("model.sbml", b"<sbml/>", "application/xml")}

    response = await http_api_client.post(
        "/curated/copasi", params=params, files=files, headers={"Authorization": f"Bearer {fake_auth0.token()}"}
    )
    assert response.status_code == 418
    assert "Curated copasi run from auth0|test-user" in caplog.text

    caplog.clear()
    response = await http_api_client.post("/curated/copasi", params=params, files=files)
    assert response.status_code == 418
    assert "Curated copasi run from anonymous" in caplog.text


def _statement_calls_describe_caller(statement: ast.stmt) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "describe_caller"
        for node in ast.walk(statement)
    )


def test_submit_simulation_logs_caller_after_any_docstring() -> None:
    """A docstring added above the log must stay the docstring. The log must not move in front of it."""
    from compose_api.api.routers.simulation import submit_simulation

    function = ast.parse(inspect.getsource(submit_simulation)).body[0]
    assert isinstance(function, ast.AsyncFunctionDef)
    string_statements = [
        index
        for index, statement in enumerate(function.body)
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    ]
    log_statements = [
        index for index, statement in enumerate(function.body) if _statement_calls_describe_caller(statement)
    ]
    assert log_statements, "submit_simulation must log describe_caller(principal)"
    if string_statements:
        assert string_statements[0] == 0, "the docstring must be the first statement, ahead of the caller log"
        assert log_statements[0] > string_statements[0]


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
async def test_submit_simulation_logs_the_caller(
    http_api_client: httpx.AsyncClient,
    fake_auth0: FakeAuth0,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stop_here(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPException(status_code=418)

    # The route dependency captured the original getters. The handler looks them up again, so patch those
    # names and stop before the upload is parsed. The caller log is what this test is here to see.
    monkeypatch.setattr("compose_api.api.routers.simulation.get_simulation_service", lambda: object())
    monkeypatch.setattr("compose_api.api.routers.simulation.get_database_service", lambda: object())
    monkeypatch.setattr("compose_api.api.routers.simulation.get_job_monitor", lambda: object())
    monkeypatch.setattr(
        "compose_api.api.routers.simulation.get_simulation_request_from_uploaded_file",
        stop_here,
    )
    files = {"uploaded_file": ("experiment.omex", b"not-a-real-archive", "application/zip")}

    response = await http_api_client.post(
        "/simulation/run",
        files=files,
        headers={"Authorization": f"Bearer {fake_auth0.token()}"},
    )
    assert response.status_code == 418
    assert "Simulation submission from auth0|test-user" in caplog.text

    caplog.clear()
    response = await http_api_client.post("/simulation/run", files=files)
    assert response.status_code == 418
    assert "Simulation submission from anonymous" in caplog.text


def test_describe_caller() -> None:
    principal = AuthenticatedPrincipal("auth0|abc", "i", ("a",), frozenset(), frozenset(), frozenset({"user"}))
    assert describe_caller(principal) == "auth0|abc"
    assert describe_caller(None) == "anonymous"


# -- the authorization seam -- #


def test_a_principal_is_a_caller() -> None:
    principal = AuthenticatedPrincipal("auth0|abc", "i", ("a",), frozenset(), frozenset(), frozenset({"user"}))
    caller: Caller = principal  # mypy checks the principal against compose_api.authorization's protocol
    assert caller.subject == "auth0|abc"
    assert caller.roles == {"user"}


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
async def test_a_verified_token_reaches_the_authorization_seam(
    http_api_client: httpx.AsyncClient,
    fake_auth0: FakeAuth0,
    database_service: DatabaseService,
    simulation_request: SimulationRequest,
    simulator: SimulatorVersion,
) -> None:
    """No get_caller override here: the caller can_read sees must be the principal the token verified to."""
    sim_db, hpc_db = database_service.get_simulator_db(), database_service.get_hpc_db()
    private = await sim_db.insert_simulation(
        sim_request=simulation_request,
        experiment_id="experiment-auth-seam",
        simulator_version=simulator,
        owner_sub="auth0|test-user",
        visibility=Visibility.PRIVATE,
    )
    run = await hpc_db.insert_hpcrun(
        slurmjobid=7201, job_type=JobType.SIMULATION, ref_id=private.database_id, correlation_id="corr-auth-seam"
    )
    params = {"simulation_id": private.database_id}
    try:
        owner = await http_api_client.get(
            "/results/simulation/status", params=params, headers={"Authorization": f"Bearer {fake_auth0.token()}"}
        )
        assert owner.status_code == 200
        assert owner.json()["trace_id"] == run.trace_id

        stranger = fake_auth0.token(sub="auth0|someone-else")
        other = await http_api_client.get(
            "/results/simulation/status", params=params, headers={"Authorization": f"Bearer {stranger}"}
        )
        assert other.status_code == 404

        assert (await http_api_client.get("/results/simulation/status", params=params)).status_code == 404

        invalid = await http_api_client.get(
            "/results/simulation/status", params=params, headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert invalid.status_code == 401
    finally:
        await hpc_db.delete_hpcrun(run.database_id)
        await sim_db.delete_simulation(private.database_id)


# -- OpenAPI -- #


def test_committed_spec_carries_the_optional_bearer() -> None:
    """The checked-in spec must be built from app.openapi(). Built with get_openapi() it would lose the bearer scheme,
    and `make check-clients` would not notice, because the committed and the regenerated copy would both lack it."""
    spec_path = Path(REPO_ROOT) / "compose_api" / "api" / "spec" / "openapi_3_1_0_generated.yaml"
    spec = yaml.safe_load(spec_path.read_text())
    assert spec["security"] == [{}, {"BearerAuth": []}]
    assert spec["components"]["securitySchemes"] == app.openapi()["components"]["securitySchemes"]
    by_operation_id = {op["operationId"]: op for path in spec["paths"].values() for op in path.values()}
    # The identity endpoint requires its bearer token; every other operation stays document-level optional.
    assert by_operation_id["get-auth-me"]["security"] == [{"BearerAuth": []}]
    rest = [op for op_id, op in by_operation_id.items() if op_id != "get-auth-me"]
    assert all("security" not in op for op in rest), "per-operation security retypes the generated client"


def test_openapi_documents_optional_bearer() -> None:
    schema = app.openapi()
    assert schema["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Optional Auth0 access token for this API. Omit it to call anonymously.",
    }
    assert schema["security"] == [{}, {"BearerAuth": []}]
    by_operation_id = {op["operationId"]: op for path in schema["paths"].values() for op in path.values()}
    # The identity endpoint requires its bearer token; every other operation stays document-level optional.
    assert by_operation_id["get-auth-me"]["security"] == [{"BearerAuth": []}]
    rest = [op for op_id, op in by_operation_id.items() if op_id != "get-auth-me"]
    assert all("security" not in op for op in rest), "per-operation security retypes the generated client"


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
    principal = AuthenticatedPrincipal("s", "i", ("a",), frozenset(), frozenset(), frozenset({"user"}))
    with pytest.raises(AttributeError):
        principal.subject = "other"  # type: ignore[misc]


@pytest.mark.parametrize("authenticated", [False, True])
def test_generated_client_keeps_optional_bearer_and_documented_404(authenticated: bool) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == ("Bearer test-token" if authenticated else None)
        assert request.url.path == "/results/simulation/status"
        assert request.url.params["simulation_id"] == "999"
        return httpx.Response(404)

    options: dict[str, Any] = {"transport": httpx.MockTransport(respond)}
    client = (
        AuthenticatedClient(base_url="https://api.test", token="test-token", httpx_args=options)  # noqa: S106 -- fake token
        if authenticated
        else Client(base_url="https://api.test", httpx_args=options)
    )
    with client:
        response = get_simulation_status.sync_detailed(client=client, simulation_id=999)
    assert response.status_code == 404
    assert response.parsed is None
