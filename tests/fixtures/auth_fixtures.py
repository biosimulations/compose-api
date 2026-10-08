import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa

from compose_api.authentication import Auth0Verifier, JwksCache

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


@pytest_asyncio.fixture
async def auth0_verifier(fake_auth0: FakeAuth0) -> AsyncGenerator[Auth0Verifier]:
    """A verifier against the fake tenant, with the production cache TTL and refresh settings."""
    jwks = JwksCache(f"{AUTH0_TEST_ISSUER}.well-known/jwks.json", transport=httpx.MockTransport(fake_auth0.handle_jwks))
    verifier = Auth0Verifier(domain=AUTH0_TEST_DOMAIN, audience=AUTH0_TEST_AUDIENCE, jwks=jwks)
    yield verifier
    await verifier.aclose()  # the cache built its own client around the mock transport
