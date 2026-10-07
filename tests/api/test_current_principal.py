"""Protected identity contract, tested through real JWT verification and the registered app."""

import time
from typing import Any, get_type_hints

import httpx
import pytest

from compose_api.api.client import AuthenticatedClient
from compose_api.api.client.api.authentication import get_current_principal
from compose_api.api.client.models.current_principal_response import CurrentPrincipalResponse
from compose_api.api.main import app
from compose_api.authentication import ROLES_CLAIM
from tests.fixtures.auth_fixtures import AUTH0_TEST_AUDIENCE, AUTH0_TEST_ISSUER, FakeAuth0


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", ["auth0|database-user", "google-oauth2|social-user", "machine@clients"])
async def test_verified_identity(
    authenticated_identity_client: httpx.AsyncClient, fake_auth0: FakeAuth0, subject: str
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
    response = await authenticated_identity_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
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
@pytest.mark.parametrize("roles", [None, "admin", {"admin": True}, [42]])
async def test_optional_claims_do_not_become_authorization_requirements(
    authenticated_identity_client: httpx.AsyncClient, fake_auth0: FakeAuth0, roles: object
) -> None:
    extra_claims: dict[str, Any] = {ROLES_CLAIM: roles}
    token = fake_auth0.token(scope=None, permissions=None, **extra_claims)
    response = await authenticated_identity_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["roles"] == ["user"]
    assert response.json()["scopes"] == response.json()["permissions"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, "", "Basic invalid", "Bearer", "Bearer malformed"])
async def test_identity_requires_bearer(authenticated_identity_client: httpx.AsyncClient, header: str | None) -> None:
    headers = {} if header is None else {"Authorization": header}
    response = await authenticated_identity_client.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid authentication credentials"}


@pytest.mark.asyncio
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
    authenticated_identity_client: httpx.AsyncClient, fake_auth0: FakeAuth0, claims: dict[str, Any]
) -> None:
    token = fake_auth0.token(**claims)
    response = await authenticated_identity_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert token not in response.text


@pytest.mark.asyncio
async def test_identity_rejects_signature_and_duplicate_headers(
    authenticated_identity_client: httpx.AsyncClient, fake_auth0: FakeAuth0
) -> None:
    extra_claims: dict[str, Any] = {ROLES_CLAIM: ["admin"]}
    forged = fake_auth0.token(signing_key=FakeAuth0().keys["key-1"], **extra_claims)
    response = await authenticated_identity_client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401
    token = fake_auth0.token()
    response = await authenticated_identity_client.get(
        "/auth/me", headers=[("Authorization", f"Bearer {token}"), ("Authorization", f"Bearer {token}")]
    )
    assert response.status_code == 401


def test_identity_route_is_registered_and_documents_required_auth() -> None:
    operation = app.openapi()["paths"]["/auth/me"]["get"]
    assert operation["operationId"] == "get-current-principal"
    assert operation["security"] == [{"BearerAuth": []}]
    assert "401" in operation["responses"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("authenticated_identity_client")
@pytest.mark.parametrize("valid", [True, False])
async def test_generated_identity_client_uses_bearer_and_handles_401(fake_auth0: FakeAuth0, valid: bool) -> None:
    token = fake_auth0.token(sub="google-oauth2|sdk-user") if valid else "invalid-test-token"
    client = AuthenticatedClient(
        base_url="http://testserver",
        token=token,
        raise_on_unexpected_status=True,
        httpx_args={"transport": httpx.ASGITransport(app=app)},
    )
    async with client:
        response = await get_current_principal.asyncio_detailed(client=client)
    assert response.status_code == (200 if valid else 401)
    if valid:
        assert isinstance(response.parsed, CurrentPrincipalResponse)
        assert response.parsed.subject == "google-oauth2|sdk-user"
        assert response.parsed.roles == ["user"]
        assert response.headers["cache-control"] == "no-store"
    else:
        assert response.parsed is None


def test_generated_identity_operation_requires_authenticated_client() -> None:
    for method in (
        get_current_principal.sync,
        get_current_principal.sync_detailed,
        get_current_principal.asyncio,
        get_current_principal.asyncio_detailed,
    ):
        assert get_type_hints(method)["client"] is AuthenticatedClient


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", ["auth0|metadata-user", "google-oauth2|metadata-user"])
async def test_untrusted_metadata_never_grants_roles(
    authenticated_identity_client: httpx.AsyncClient, fake_auth0: FakeAuth0, subject: str
) -> None:
    token = fake_auth0.token(sub=subject, user_metadata={"roles": ["admin"]}, connection={"role": "admin"})
    response = await authenticated_identity_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["roles"] == ["user"]
