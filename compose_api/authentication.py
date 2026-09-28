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
# Bound outage fallback so a removed signing key cannot remain trusted indefinitely.
JWKS_MAX_STALE_SECONDS = 86400.0
# Back-off for re-fetching an expired cache while its keys still verify, so a JWKS outage serves the cached keys
# instead of stalling every request on a fetch. Never delays the refresh for an unknown kid.
JWKS_MIN_REFRESH_INTERVAL_SECONDS = 30.0
JWKS_TIMEOUT_SECONDS = 5.0
# Tolerated clock difference between Auth0 and this host for exp/iat/nbf. Without it a fresh token is rejected
# whenever this host's clock is even a second behind Auth0's (PyJWT rejects iat > now). Auth0's own Python SDK
# (TokenVerifier) defaults to the same 60 s.
JWT_LEEWAY_SECONDS = 60

# Every verified caller holds DEFAULT_ROLE; an anonymous caller has no principal and so no role. It is the tenant-wide
# Auth0 role "user" owned by auth0-pulumi/biosim-platform (roles.py: biosim_user_role) -- keep the spelling in step.
DEFAULT_ROLE = "user"
# Namespaced claim in which the tenant's "BioSim Roles" post-login Action lists the caller's Auth0 role names. Only
# tokens issued to a logged-in user carry it; client-credentials (M2M) tokens never do.
ROLES_CLAIM = "https://api.biosimulations.org/roles"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    subject: str
    issuer: str
    audience: tuple[str, ...]
    scopes: frozenset[str]
    permissions: frozenset[str]
    roles: frozenset[str]  # always contains DEFAULT_ROLE; roles identify the caller, they do not authorize anything yet


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
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        ttl_seconds: float = JWKS_TTL_SECONDS,
        max_stale_seconds: float = JWKS_MAX_STALE_SECONDS,
        min_refresh_interval_seconds: float = JWKS_MIN_REFRESH_INTERVAL_SECONDS,
    ) -> None:
        """`client` is the reusable client a long-running service injects so JWKS fetches share its connection pool.
        Passing `transport` instead builds a private client around that transport; that is the test seam."""
        self._jwks_url = jwks_url
        self._client = client or httpx.AsyncClient(transport=transport, timeout=JWKS_TIMEOUT_SECONDS)
        self._owns_client = client is None
        self._ttl_seconds = ttl_seconds
        self._max_stale_seconds = max_stale_seconds
        self._min_refresh_interval_seconds = min_refresh_interval_seconds

        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._attempted_at: float | None = None
        self._refresh_attempts = 0
        self._lock = asyncio.Lock()

    async def get_key(self, kid: str) -> jwt.PyJWK:
        key = self._keys.get(kid)
        if key is not None and self._is_usable() and (self._is_fresh() or not self._may_refresh()):
            return key
        if key is not None and not self._is_usable() and not self._may_refresh():
            raise AuthenticationError("jwks_unavailable")
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
        if not self._is_usable():
            raise AuthenticationError("jwks_unavailable")
        return key

    def _is_usable(self) -> bool:
        return self._fetched_at is not None and time.monotonic() - self._fetched_at < self._max_stale_seconds

    def _is_fresh(self) -> bool:
        return self._fetched_at is not None and time.monotonic() - self._fetched_at < self._ttl_seconds

    def _may_refresh(self) -> bool:
        return self._attempted_at is None or time.monotonic() - self._attempted_at >= self._min_refresh_interval_seconds

    async def aclose(self) -> None:
        """Release the private client built from `transport`. A client injected by the caller is left alone."""
        if self._owns_client:
            await self._client.aclose()

    async def _refresh(self) -> None:
        self._attempted_at = time.monotonic()
        try:
            response = await self._client.get(self._jwks_url)
            response.raise_for_status()

            document = response.json()

            if not isinstance(document, dict):
                raise jwt.PyJWKSetError("Invalid JWKS document")

            jwk_set = jwt.PyJWKSet.from_dict(document)

        except (httpx.HTTPError, ValueError, jwt.PyJWTError):
            logger.warning("Could not refresh Auth0 JWKS; keeping %d cached key(s)", len(self._keys))

            if not self._keys:
                raise AuthenticationError("jwks_unavailable") from None
            return

        keys = {
            key.key_id: key
            for key in jwk_set.keys
            if (
                isinstance(key.key_id, str)
                and key.key_id
                and key.algorithm_name in ALLOWED_ALGORITHMS
                and key.public_key_use in (None, "sig")
            )
        }

        if not keys:
            logger.warning("Auth0 JWKS contained no usable signing keys")
            raise AuthenticationError("jwks_unavailable")
        self._keys = keys
        self._fetched_at = time.monotonic()


class Auth0Verifier:
    # Verifiers this module constructed, and therefore owns the HTTP client of, so lifespan shutdown can close them.
    _owned_verifiers: list["Auth0Verifier"] = []

    def __init__(
        self,
        domain: str,
        audience: str,
        jwks: JwksCache | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.issuer = f"https://{domain}/"
        self.audience = audience
        self._jwks = jwks or JwksCache(f"https://{domain}/.well-known/jwks.json", client=client)
        if jwks is None:
            # Built our own cache, so we own whatever client is behind it; lifespan shutdown closes it. A caller
            # that passed `jwks` (or injected its own `client`) keeps ownership of that transport.
            Auth0Verifier._owned_verifiers.append(self)

    async def aclose(self) -> None:
        await self._jwks.aclose()

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


def _principal_from_claims(
    claims: dict[str, Any],
) -> AuthenticatedPrincipal:
    subject = claims.get("sub")
    issuer = claims.get("iss")
    audience = claims.get("aud")

    if not isinstance(subject, str) or not subject:
        raise AuthenticationError("missing_claim")

    if not isinstance(issuer, str) or not issuer:
        raise AuthenticationError("missing_claim")

    if isinstance(audience, str) and audience:
        audiences = (audience,)
    elif isinstance(audience, list) and audience and all(isinstance(item, str) and item for item in audience):
        audiences = tuple(audience)
    else:
        raise AuthenticationError("invalid_audience")

    scope = claims.get("scope")

    return AuthenticatedPrincipal(
        subject=subject,
        issuer=issuer,
        audience=audiences,
        scopes=(frozenset(scope.split()) if isinstance(scope, str) else frozenset()),
        permissions=_string_set(claims.get("permissions")),
        roles=(frozenset({DEFAULT_ROLE}) | _string_set(claims.get(ROLES_CLAIM))),
    )


def _string_set(value: object) -> frozenset[str]:
    """The strings in a list-valued claim; anything else (absent, a bare string, a number) contributes nothing."""
    return frozenset(item for item in value if isinstance(item, str)) if isinstance(value, list) else frozenset()


@lru_cache(maxsize=4)
def _build_verifier(domain: str, audience: str) -> Auth0Verifier:
    return Auth0Verifier(domain=domain, audience=audience)


async def aclose_verifiers() -> None:
    """Close the HTTP client behind each verifier this process built, then drop them.

    Verifiers passed in by a caller (tests, or an app injecting a shared client) own their own transport and are
    never registered here. Call from the FastAPI lifespan alongside the other services.
    """
    _build_verifier.cache_clear()
    verifiers, Auth0Verifier._owned_verifiers[:] = list(Auth0Verifier._owned_verifiers), []
    for verifier in verifiers:
        await verifier.aclose()


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


async def get_required_principal(
    principal: Annotated[
        AuthenticatedPrincipal | None,
        Depends(get_optional_principal),
    ],
) -> AuthenticatedPrincipal:
    """
    FastAPI dependency requiring a successfully authenticated caller.

    Missing credentials are rejected with 401. Invalid supplied credentials
    have already been rejected by get_optional_principal().
    """
    if principal is None:
        raise _unauthorized()

    return principal


OptionalPrincipal = Annotated[AuthenticatedPrincipal | None, Depends(get_optional_principal)]
RequiredPrincipal = Annotated[AuthenticatedPrincipal, Depends(get_required_principal)]


def describe_caller(principal: AuthenticatedPrincipal | None) -> str:
    """The caller for a log line: the verified subject, or "anonymous". Never includes token data."""
    return principal.subject if principal is not None else "anonymous"
