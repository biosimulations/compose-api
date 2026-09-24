"""Optional Auth0 bearer-token authentication.

A request with no Authorization header is anonymous. A request that supplies one must carry a valid
Auth0 access token for this API, or it is rejected with 401 -- a bad credential is never downgraded
to anonymous. Authorization (what a principal may do) is deliberately out of scope here.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status

from compose_api.config import get_settings

logger = logging.getLogger(__name__)

# Never taken from the token header: a token advertising any other alg is rejected before decoding.
ALLOWED_ALGORITHMS = ("RS256",)
BEARER_SCHEME_NAME = "BearerAuth"
JWKS_TTL_SECONDS = 600.0
# Back-off for re-fetching an expired cache while its keys still verify, so a JWKS outage serves the cached keys
# instead of stalling every request on a fetch. Never delays the refresh for an unknown kid.
JWKS_MIN_REFRESH_INTERVAL_SECONDS = 30.0
JWKS_TIMEOUT_SECONDS = 5.0
# Tolerated clock difference between Auth0 and this host for exp/iat/nbf. Without it a fresh token is rejected
# whenever this host's clock is even a second behind Auth0's (PyJWT rejects iat > now). Auth0's own Python SDK
# (TokenVerifier) defaults to the same 60 s.
JWT_LEEWAY_SECONDS = 60


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    subject: str
    issuer: str
    audience: tuple[str, ...]
    scopes: frozenset[str]
    permissions: frozenset[str]


class AuthenticationError(Exception):
    """A supplied credential failed verification. `category` is safe to log; the message never holds token data."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class JwksCache:
    """Process-local cache of the tenant's signing keys.

    An unknown kid always triggers one refresh, because Auth0 may just have rotated its signing key; requests that
    arrive while that refresh is in flight reuse its result rather than fetching again. A known kid whose entry has
    passed its TTL is refreshed at most once per `min_refresh_interval_seconds`.
    """

    def __init__(
        self,
        jwks_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        ttl_seconds: float = JWKS_TTL_SECONDS,
        min_refresh_interval_seconds: float = JWKS_MIN_REFRESH_INTERVAL_SECONDS,
    ) -> None:
        self._jwks_url = jwks_url
        self._transport = transport
        self._ttl_seconds = ttl_seconds
        self._min_refresh_interval_seconds = min_refresh_interval_seconds
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._attempted_at: float | None = None
        self._refresh_attempts = 0
        self._lock = asyncio.Lock()

    async def get_key(self, kid: str) -> jwt.PyJWK:
        key = self._keys.get(kid)
        if key is not None and (self._is_fresh() or not self._may_refresh()):
            return key
        attempts_seen = self._refresh_attempts
        async with self._lock:
            # Coalesce: if a refresh ran while this request waited for the lock, use its result.
            if self._refresh_attempts == attempts_seen:
                try:
                    await self._refresh()
                finally:
                    # Counted on completion, success or failure, so requests that arrived mid-refresh reuse it.
                    self._refresh_attempts += 1
        key = self._keys.get(kid)
        if key is None:
            raise AuthenticationError("unknown_kid")
        return key

    def _is_fresh(self) -> bool:
        return self._fetched_at is not None and time.monotonic() - self._fetched_at < self._ttl_seconds

    def _may_refresh(self) -> bool:
        return self._attempted_at is None or time.monotonic() - self._attempted_at >= self._min_refresh_interval_seconds

    async def _refresh(self) -> None:
        self._attempted_at = time.monotonic()
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=JWKS_TIMEOUT_SECONDS) as client:
                response = await client.get(self._jwks_url)
                response.raise_for_status()
            jwk_set = jwt.PyJWKSet.from_dict(response.json())
        except (httpx.HTTPError, ValueError, jwt.PyJWTError):
            # Keep serving the previous keys: a transient outage should not reject tokens signed by a known key.
            logger.warning("Could not refresh Auth0 JWKS; keeping %d cached key(s)", len(self._keys))
            if not self._keys:
                raise AuthenticationError("jwks_unavailable") from None
            return
        self._keys = {key.key_id: key for key in jwk_set.keys if key.key_id}
        self._fetched_at = time.monotonic()


class Auth0Verifier:
    def __init__(self, domain: str, audience: str, jwks: JwksCache | None = None) -> None:
        self.issuer = f"https://{domain}/"
        self.audience = audience
        self._jwks = jwks or JwksCache(f"https://{domain}/.well-known/jwks.json")

    async def verify(self, token: str) -> AuthenticatedPrincipal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise AuthenticationError("malformed_token") from None
        if header.get("alg") not in ALLOWED_ALGORITHMS:
            raise AuthenticationError("unsupported_algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AuthenticationError("missing_kid")
        key = await self._jwks.get_key(kid)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
                leeway=JWT_LEEWAY_SECONDS,
            )
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("token_expired") from None
        except jwt.InvalidAudienceError:
            raise AuthenticationError("invalid_audience") from None
        except jwt.InvalidIssuerError:
            raise AuthenticationError("invalid_issuer") from None
        except jwt.InvalidSignatureError:
            raise AuthenticationError("invalid_signature") from None
        except jwt.MissingRequiredClaimError:
            raise AuthenticationError("missing_claim") from None
        except jwt.PyJWTError:
            raise AuthenticationError("invalid_token") from None
        return _principal_from_claims(claims)


def _principal_from_claims(claims: dict[str, Any]) -> AuthenticatedPrincipal:
    subject = claims["sub"]
    if not isinstance(subject, str) or not subject:
        raise AuthenticationError("missing_claim")
    audience = claims["aud"]
    scope = claims.get("scope")
    permissions = claims.get("permissions")
    return AuthenticatedPrincipal(
        subject=subject,
        issuer=claims["iss"],
        audience=(audience,) if isinstance(audience, str) else tuple(audience),
        scopes=frozenset(scope.split()) if isinstance(scope, str) else frozenset(),
        permissions=frozenset(p for p in permissions if isinstance(p, str))
        if isinstance(permissions, list)
        else frozenset(),
    )


@lru_cache(maxsize=4)
def _build_verifier(domain: str, audience: str) -> Auth0Verifier:
    return Auth0Verifier(domain=domain, audience=audience)


def get_auth0_verifier() -> Auth0Verifier | None:
    """The verifier for the configured tenant, or None when Auth0 is not configured.

    Cached per (domain, audience) rather than once, so settings are resolved at use and
    `override_settings` still takes effect.
    """
    settings = get_settings()
    if not settings.auth0_domain or not settings.auth0_audience:
        return None
    return _build_verifier(settings.auth0_domain, settings.auth0_audience)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _parse_bearer_token(request: Request) -> str | None:
    """The bearer token, None when no Authorization header was sent, or AuthenticationError if one is malformed.

    Deliberately not fastapi.security.HTTPBearer: with auto_error=False it returns None for a
    non-Bearer scheme or an empty token too, which would turn a malformed credential into anonymous.
    """
    values = request.headers.getlist("authorization")
    if not values:
        return None
    if len(values) > 1:
        raise AuthenticationError("malformed_credentials")
    parts = values[0].split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthenticationError("malformed_credentials")
    return parts[1]


async def _authenticate(request: Request, verifier: Auth0Verifier | None) -> AuthenticatedPrincipal | None:
    token = _parse_bearer_token(request)
    if token is None:
        return None
    if verifier is None:
        raise AuthenticationError("auth_not_configured")
    return await verifier.verify(token)


async def get_optional_principal(
    request: Request,
    verifier: Annotated[Auth0Verifier | None, Depends(get_auth0_verifier)],
) -> AuthenticatedPrincipal | None:
    """FastAPI dependency: None for an anonymous request, a principal for a valid token, 401 otherwise."""
    try:
        return await _authenticate(request, verifier)
    except AuthenticationError as e:
        logger.info("Rejected bearer credentials: %s", e.category)
        raise _unauthorized() from None


OptionalPrincipal = Annotated[AuthenticatedPrincipal | None, Depends(get_optional_principal)]


def describe_caller(principal: AuthenticatedPrincipal | None) -> str:
    """The caller for a log line: the verified subject, or "anonymous". Never includes token data."""
    return principal.subject if principal is not None else "anonymous"
