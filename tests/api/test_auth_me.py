"""GET /auth/me: the verified bearer identity, and nothing else.

Through the real app with a fake Auth0 tenant: no token is 401, a valid Compose access token reports the
verified identity, and anything else (wrong issuer/audience, expiry, forgery, an ID token minted for a client
rather than this API) is rejected. Anonymous public routes are unaffected (pinned in test_authentication.py).
"""

import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
import yaml

from compose_api.api.main import app
from compose_api.authentication import (
    DEFAULT_ROLE,
    ROLES_CLAIM,
    Auth0Verifier,
    get_auth0_verifier,
)
from compose_api.config import REPO_ROOT
from tests.fixtures.auth_fixtures import AUTH0_TEST_AUDIENCE, AUTH0_TEST_ISSUER, FakeAuth0

COMMITTED_SPEC = Path(REPO_ROOT) / "compose_api" / "api" / "spec" / "openapi_3_1_0_generated.yaml"


@pytest_asyncio.fixture
async def app_with_test_auth0(auth0_verifier: Auth0Verifier) -> AsyncGenerator[None]:
    app.dependency_overrides[get_auth0_verifier] = lambda: auth0_verifier
    yield
    del app.dependency_overrides[get_auth0_verifier]


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
@pytest.mark.parametrize("subject", ["auth0|database-user", "google-oauth2|social-user", "machine@clients"])
async def test_valid_token_reports_the_verified_identity(
    http_api_client: httpx.AsyncClient, fake_auth0: FakeAuth0, subject: str
) -> None:
    extra_claims: dict[str, Any] = {
        ROLES_CLAIM: ["publisher", "user"],
        "email": "private@example.test",
        "email_verified": False,
    }
    token = fake_auth0.token(
        sub=subject,
        scope="profile openid profile",
        permissions=["write:example", "read:example", "read:example"],
        **extra_claims,
    )
    response = await http_api_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "issuer": AUTH0_TEST_ISSUER,
        "subject": subject,
        "audience": sorted([AUTH0_TEST_AUDIENCE, f"{AUTH0_TEST_ISSUER}userinfo"]),
        "roles": ["publisher", "user"],
        "scopes": ["openid", "profile"],
        "permissions": ["read:example", "write:example"],
    }
    assert token not in response.text
    assert fake_auth0.jwks_requests == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
@pytest.mark.parametrize("roles", [None, "admin", {"admin": True}, [42]])
async def test_optional_claims_do_not_become_authorization_requirements(
    http_api_client: httpx.AsyncClient, fake_auth0: FakeAuth0, roles: object
) -> None:
    extra_claims: dict[str, Any] = {ROLES_CLAIM: roles}
    token = fake_auth0.token(scope=None, permissions=None, **extra_claims)
    response = await http_api_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["roles"] == [DEFAULT_ROLE]
    assert response.json()["scopes"] == response.json()["permissions"] == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
@pytest.mark.parametrize("header", [None, "", "Basic invalid", "Bearer", "Bearer malformed"])
async def test_identity_requires_bearer(http_api_client: httpx.AsyncClient, header: str | None) -> None:
    headers = {} if header is None else {"Authorization": header}
    response = await http_api_client.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid authentication credentials"}


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://foreign.example/"},
        {"aud": "https://other-api.example"},
        {"exp": 1},
        {"exp": None},
        {"iat": None},
        {"sub": None},
        {"sub": ""},
        {"nbf": time.time() + 3600},
    ],
)
async def test_identity_rejects_invalid_claims(
    http_api_client: httpx.AsyncClient, fake_auth0: FakeAuth0, claims: dict[str, Any]
) -> None:
    token = fake_auth0.token(**claims)
    response = await http_api_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert token not in response.text


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
async def test_identity_rejects_an_id_token_minted_for_a_client(
    http_api_client: httpx.AsyncClient, fake_auth0: FakeAuth0
) -> None:
    """An ID token's audience is the native client, not this API: it identifies the user to the client,
    it does not authorize API calls, so /auth/me must reject it."""
    token = fake_auth0.token(aud="compose-cli-native-client-id")
    response = await http_api_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert token not in response.text


@pytest.mark.asyncio
@pytest.mark.usefixtures("app_with_test_auth0")
async def test_identity_rejects_signature_and_duplicate_headers(
    http_api_client: httpx.AsyncClient, fake_auth0: FakeAuth0
) -> None:
    extra_claims: dict[str, Any] = {ROLES_CLAIM: ["admin"]}
    forged = fake_auth0.token(signing_key=FakeAuth0().keys["key-1"], **extra_claims)
    response = await http_api_client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401
    token = fake_auth0.token()
    response = await http_api_client.get(
        "/auth/me", headers=[("Authorization", f"Bearer {token}"), ("Authorization", f"Bearer {token}")]
    )
    assert response.status_code == 401


def test_identity_route_is_registered_and_documents_required_auth() -> None:
    """Router registration failures are logged and swallowed, so assert the served app actually exposes the
    route (its flattened OpenAPI paths) — alongside the committed spec carrying the same operation."""
    served = app.openapi()["paths"]
    assert "/auth/me" in served
    operation = served["/auth/me"]["get"]
    assert operation["operationId"] == "get-auth-me"
    assert operation["security"] == [{"BearerAuth": []}]
    assert "401" in operation["responses"]

    spec = yaml.safe_load(COMMITTED_SPEC.read_text())
    assert spec["paths"]["/auth/me"]["get"]["operationId"] == "get-auth-me"
