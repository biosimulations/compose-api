import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa

from compose_api.api.main import app
from compose_api.authentication import Auth0Verifier, JwksCache, get_auth0_verifier

AUTH0_TEST_DOMAIN = "compose-test.example.auth0.com"
AUTH0_TEST_ISSUER = f"https://{AUTH0_TEST_DOMAIN}/"
AUTH0_TEST_AUDIENCE = "https://compose-api.test"


class FakeAuth0:
    """Stands in for an Auth0 tenant: holds RSA signing keys, serves them as JWKS, and mints tokens."""

    def __init__(self) -> None:
        self.keys: dict[str, rsa.RSAPrivateKey] = {}
        self.jwks_requests = 0
        self.jwks_available = True
        self.add_key("key-1")

    def add_key(self, kid: str) -> rsa.RSAPrivateKey:
        self.keys[kid] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return self.keys[kid]

    def handle_jwks(self, _request: httpx.Request) -> httpx.Response:
        self.jwks_requests += 1
        if not self.jwks_available:
            return httpx.Response(503)
        keys = [
            {**jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True), "kid": kid, "use": "sig"}
            for kid, key in self.keys.items()
        ]
        return httpx.Response(200, json={"keys": keys})

    def token(self, kid: str = "key-1", signing_key: rsa.RSAPrivateKey | None = None, **claim_overrides: Any) -> str:
        """An RS256 access token; pass a claim as None to omit it."""
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": "auth0|test-user",
            "iss": AUTH0_TEST_ISSUER,
            "aud": [AUTH0_TEST_AUDIENCE, f"{AUTH0_TEST_ISSUER}userinfo"],
            "iat": now,
            "exp": now + 300,
            "scope": "openid profile",
        }
        claims.update(claim_overrides)
        claims = {name: value for name, value in claims.items() if value is not None}
        return jwt.encode(claims, signing_key or self.keys[kid], algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def fake_auth0() -> FakeAuth0:
    return FakeAuth0()


@pytest.fixture
def auth0_verifier(fake_auth0: FakeAuth0) -> Auth0Verifier:
    """A verifier against the fake tenant, with the production cache TTL and refresh settings."""
    jwks = JwksCache(f"{AUTH0_TEST_ISSUER}.well-known/jwks.json", transport=httpx.MockTransport(fake_auth0.handle_jwks))
    return Auth0Verifier(domain=AUTH0_TEST_DOMAIN, audience=AUTH0_TEST_AUDIENCE, jwks=jwks)


@pytest_asyncio.fixture
async def authenticated_identity_client(auth0_verifier: Auth0Verifier) -> AsyncGenerator[httpx.AsyncClient]:
    """Real router/verification, without starting the HPC lifespan or replacing authentication itself."""
    previous = app.dependency_overrides.get(get_auth0_verifier)
    app.dependency_overrides[get_auth0_verifier] = lambda: auth0_verifier
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            yield client
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_auth0_verifier, None)
        else:
            app.dependency_overrides[get_auth0_verifier] = previous
        await auth0_verifier.aclose()
