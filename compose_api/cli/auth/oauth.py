"""Auth0 as the CLI sees it: discovery, authorization URLs, the token, device and revocation endpoints, and the
validation of everything they return.

HTTP is a plain httpx client with its policy spelled out here: finite timeouts, TLS verification, no redirects, no
proxy or credentials taken from the environment, bounded response bodies, and never a bearer token. Authlib supplies
protocol pieces -- the authorization URL, the PKCE S256 challenge and the OIDC ID-token claim rules -- but not its
HTTP clients: those refresh tokens and attach bearers on their own, and refresh belongs to the session layer.

A token response becomes a `TokenGrant` only after every check passes; a response that fails any check is dropped
whole, so nothing unvalidated can be stored or sent to the API. Error messages name the check that failed, never a
token, a code or the server's own error description.
"""

import asyncio
import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Self
from urllib.parse import urlsplit

import httpx
import jwt
from authlib.oauth2.rfc6749.parameters import prepare_grant_uri
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from authlib.oidc.core import CodeIDToken
from joserfc.errors import JoseError
from pydantic import SecretStr

from compose_api.cli.auth.models import AuthTransaction, Identity, TokenGrant
from compose_api.cli.config import OFFLINE_ACCESS_SCOPE, CliSettings
from compose_api.cli.errors import AuthError, CliError, NetworkError, ProtocolError
from compose_api.version import __version__

# The same contract the API enforces (compose_api.authentication), restated rather than imported: that module
# loads the server's configuration. tests/cli/test_oauth.py keeps the two in step.
ALGORITHMS: Final = ("RS256",)  # fixed here, never taken from a token header
LEEWAY_SECONDS: Final = 60
REQUIRED_CLAIMS: Final = ("exp", "iat", "iss", "aud", "sub")

DEVICE_CODE_GRANT: Final = "urn:ietf:params:oauth:grant-type:device_code"
# A token closer to expiry than this on arrival is useless: the session layer renews this early.
MIN_USEFUL_LIFETIME_SECONDS: Final = 60
MAX_EXPIRES_IN_SECONDS: Final = 30 * 86400
MAX_RESPONSE_BYTES: Final = 64 * 1024
MAX_TOKEN_CHARS: Final = 16 * 1024
JWKS_MIN_REFRESH_INTERVAL_SECONDS: Final = 30.0
REQUEST_DEADLINE_SECONDS: Final = 20.0
TIMEOUT: Final = httpx.Timeout(15.0, connect=5.0)

_ERROR_CODE = re.compile(r"[a-z0-9_]{1,64}")
_REDIRECT_STATUSES = range(300, 400)


class OAuthErrorResponse(Exception):
    """An OAuth error answer from the token or device endpoint. Carries the error code only: the description is
    free text from the server and is never shown."""

    def __init__(self, error: str, status: int) -> None:
        super().__init__(error or f"HTTP {status}")
        self.error = error
        self.status = status


@dataclass(frozen=True)
class ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    device_authorization_endpoint: str | None
    revocation_endpoint: str | None


class Auth0OAuthClient:
    """One tenant, one public client. Holds no token: every call takes what it needs and returns what it got."""

    def __init__(
        self,
        settings: CliSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.client_id = settings.require_client_id()
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=TIMEOUT,
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json", "User-Agent": f"compose-api-cli/{__version__}"},
        )
        self._monotonic = monotonic
        self._metadata: ProviderMetadata | None = None
        self._keys: dict[str, jwt.PyJWK] = {}
        self._keys_fetched_at: float | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def metadata(self) -> ProviderMetadata:
        """The tenant's endpoints, discovered only at the configured issuer and only if they stay on its host."""
        if self._metadata is None:
            url = f"{self.settings.issuer}.well-known/openid-configuration"
            status, document = await self._request("GET", url)
            _require_ok(status, document, url)
            self._metadata = _parse_metadata(document, self.settings)
        return self._metadata

    async def authorization_url(
        self,
        transaction: AuthTransaction,
        *,
        connection: str | None = None,
        screen_hint: str | None = None,
        prompt: str | None = None,
    ) -> str:
        """The `/authorize` URL for one transaction. It carries the S256 challenge, never the verifier."""
        metadata = await self.metadata()
        url = prepare_grant_uri(
            metadata.authorization_endpoint,
            client_id=self.client_id,
            response_type="code",
            redirect_uri=transaction.redirect_uri,
            scope=" ".join(transaction.scopes),
            state=transaction.state,
            nonce=transaction.nonce,
            audience=self.settings.auth0_audience,
            code_challenge=create_s256_code_challenge(transaction.code_verifier),
            code_challenge_method="S256",
            connection=connection,
            screen_hint=screen_hint,
            prompt=prompt,
        )
        return str(url)

    async def exchange_code(self, transaction: AuthTransaction, code: str) -> TokenGrant:
        """Redeem an authorization code once. A failure, including a timeout, is never retried with the same code."""
        metadata = await self.metadata()
        form = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "code_verifier": transaction.code_verifier,
            "redirect_uri": transaction.redirect_uri,
        }
        try:
            payload = await self._oauth_post(metadata.token_endpoint, form)
        except OAuthErrorResponse as exc:
            raise token_failure(exc, "the sign-in code")
        return await self._validate_grant(payload, requested_scopes=transaction.scopes, nonce=transaction.nonce)

    async def device_authorization(self, scopes: tuple[str, ...]) -> dict[str, Any]:
        """Start a device sign-in. The raw answer is validated by `device.parse_device_authorization`."""
        metadata = await self.metadata()
        if metadata.device_authorization_endpoint is None:
            raise ProtocolError("the tenant does not offer device sign-in; sign in in a browser instead")
        form = {"client_id": self.client_id, "scope": " ".join(scopes), "audience": self.settings.auth0_audience}
        try:
            return await self._oauth_post(metadata.device_authorization_endpoint, form)
        except OAuthErrorResponse as exc:
            raise token_failure(exc, "device sign-in")

    async def device_token(self, device_code: str, scopes: tuple[str, ...]) -> TokenGrant:
        """Poll once. Pending, slow-down and the other device errors surface as OAuthErrorResponse."""
        metadata = await self.metadata()
        form = {"grant_type": DEVICE_CODE_GRANT, "device_code": device_code, "client_id": self.client_id}
        payload = await self._oauth_post(metadata.token_endpoint, form)
        # Device authorization has no nonce parameter, so none is expected in the ID token.
        return await self._validate_grant(payload, requested_scopes=scopes, nonce=None)

    async def refresh(self, refresh_token: SecretStr, scopes: tuple[str, ...]) -> TokenGrant:
        """Exchange a refresh token. The result's refresh token is exactly what Auth0 returned -- None if it sent none.

        It is never back-filled with the token just spent: with rotation on, that token is already used up.
        """
        metadata = await self.metadata()
        form = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token.get_secret_value(),
        }
        try:
            payload = await self._oauth_post(metadata.token_endpoint, form)
        except OAuthErrorResponse as exc:
            raise token_failure(exc, "the session renewal")
        return await self._validate_grant(payload, requested_scopes=scopes, nonce=None, require_id_token=False)

    async def revoke(self, refresh_token: SecretStr) -> None:
        metadata = await self.metadata()
        if metadata.revocation_endpoint is None:
            raise ProtocolError("the tenant does not advertise token revocation")
        form = {
            "client_id": self.client_id,
            "token": refresh_token.get_secret_value(),
            "token_type_hint": "refresh_token",
        }
        status, payload = await self._request("POST", metadata.revocation_endpoint, form=form)
        if status == 200:
            return
        if status >= 500 or status == 429:
            raise NetworkError(f"Auth0 could not revoke the session right now (HTTP {status}); try again later")
        raise ProtocolError(f"Auth0 refused to revoke the session ({_error_code(payload) or f'HTTP {status}'})")

    async def _validate_grant(
        self,
        payload: dict[str, Any],
        *,
        requested_scopes: tuple[str, ...],
        nonce: str | None,
        require_id_token: bool = True,
    ) -> TokenGrant:
        received_at = time.time()
        access_token = _token_string(payload.get("access_token"), "access_token")
        token_type = payload.get("token_type")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            raise ProtocolError("the token response is not a Bearer token")
        expires_in = payload.get("expires_in")
        if type(expires_in) is not int or not 0 < expires_in <= MAX_EXPIRES_IN_SECONDS:
            raise ProtocolError("the token response has a missing or malformed expires_in")
        scopes = _granted_scopes(payload.get("scope"), requested_scopes)
        refresh_token = payload.get("refresh_token")
        if refresh_token is not None:
            refresh_token = _token_string(refresh_token, "refresh_token")
        if OFFLINE_ACCESS_SCOPE not in requested_scopes:
            # A session that did not ask for offline access never keeps it, even if the tenant grants it anyway.
            refresh_token = None
            scopes = tuple(scope for scope in scopes if scope != OFFLINE_ACCESS_SCOPE)

        access_claims = await self._verify_access_token(access_token)
        identity = Identity(issuer=access_claims["iss"], subject=access_claims["sub"])
        id_token = payload.get("id_token")
        if id_token is None and require_id_token:
            raise ProtocolError("the token response has no ID token")
        if id_token is not None:
            id_claims = await self._verify_id_token(_token_string(id_token, "id_token"), nonce, access_token)
            if id_claims["sub"] != identity.subject:
                raise ProtocolError("the ID token and the access token name different users")

        expires_at = min(float(access_claims["exp"]), received_at + expires_in)
        if expires_at - time.time() < MIN_USEFUL_LIFETIME_SECONDS:
            raise ProtocolError(
                "the access token expires within a minute of arriving; check that this computer's clock is correct"
            )
        return TokenGrant(
            identity=identity,
            access_token=SecretStr(access_token),
            access_token_expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
            refresh_token=None if refresh_token is None else SecretStr(refresh_token),
            scopes=scopes,
            received_at=datetime.fromtimestamp(received_at, tz=UTC),
        )

    async def _verify_access_token(self, token: str) -> dict[str, Any]:
        """The API's own checks: RS256, this tenant's key, this issuer, this API's audience, required claims."""
        key = await self._signing_key(token, "access token")
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=list(ALGORITHMS),
                audience=self.settings.auth0_audience,
                issuer=self.settings.issuer,
                options={"require": list(REQUIRED_CLAIMS)},
                leeway=LEEWAY_SECONDS,
            )
        except jwt.PyJWTError as exc:
            raise ProtocolError(f"the access token was rejected: {_jwt_reason(exc)}")
        if not isinstance(claims["sub"], str) or not claims["sub"]:
            raise ProtocolError("the access token was rejected: its subject is empty")
        return claims

    async def _verify_id_token(self, token: str, nonce: str | None, access_token: str) -> dict[str, Any]:
        """Signature and registered claims with PyJWT, then the OIDC rules (nonce, azp, at_hash) with Authlib."""
        key = await self._signing_key(token, "ID token")
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=list(ALGORITHMS),
                audience=self.client_id,
                issuer=self.settings.issuer,
                options={"require": list(REQUIRED_CLAIMS)},
                leeway=LEEWAY_SECONDS,
            )
        except jwt.PyJWTError as exc:
            raise ProtocolError(f"the ID token was rejected: {_jwt_reason(exc)}")
        oidc = CodeIDToken(
            claims,
            jwt.get_unverified_header(token),  # the header just verified with the signature
            {
                "iss": {"essential": True, "value": self.settings.issuer},
                "aud": {"essential": True, "value": self.client_id},
                "sub": {"essential": True},
            },
            {"nonce": nonce, "client_id": self.client_id, "access_token": access_token},
        )
        try:
            oidc.validate(now=int(time.time()), leeway=LEEWAY_SECONDS)
        except JoseError as exc:
            raise ProtocolError(f"the ID token was rejected: {_oidc_reason(exc)}")
        return claims

    async def _signing_key(self, token: str, what: str) -> jwt.PyJWK:
        """The tenant key a token names. The algorithm is checked first and fixed; no URL in the header is used."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            hint = "; check auth0_audience" if what == "access token" else ""
            raise ProtocolError(f"the {what} is not a signed JWT{hint}")
        if header.get("alg") not in ALGORITHMS:
            raise ProtocolError(f"the {what} is not signed with {', '.join(ALGORITHMS)}")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise ProtocolError(f"the {what} does not name its signing key")
        key = self._keys.get(kid)
        if key is None and (
            self._keys_fetched_at is None
            or self._monotonic() - self._keys_fetched_at >= JWKS_MIN_REFRESH_INTERVAL_SECONDS
        ):
            await self._fetch_keys()
            key = self._keys.get(kid)
        if key is None:
            raise ProtocolError(f"the {what} is signed with a key the tenant does not publish")
        return key

    async def _fetch_keys(self) -> None:
        metadata = await self.metadata()
        status, document = await self._request("GET", metadata.jwks_uri)
        _require_ok(status, document, metadata.jwks_uri)
        try:
            key_set = jwt.PyJWKSet.from_dict(document)
        except jwt.PyJWTError:
            raise ProtocolError("the tenant's signing keys could not be read")
        self._keys = {
            key.key_id: key
            for key in key_set.keys
            if isinstance(key.key_id, str)
            and key.key_id
            and key.algorithm_name in ALGORITHMS
            and key.public_key_use in (None, "sig")
        }
        self._keys_fetched_at = self._monotonic()

    async def _oauth_post(self, url: str, form: Mapping[str, str]) -> dict[str, Any]:
        """POST to the token or device endpoint: a 200 JSON object, or OAuthErrorResponse for an OAuth error."""
        status, payload = await self._request("POST", url, form=form)
        if status == 200:
            if not isinstance(payload, dict):
                raise ProtocolError(f"Auth0 sent a malformed response from {_path(url)}")
            return payload
        if status >= 500:
            raise NetworkError(f"Auth0 is unavailable (HTTP {status} from {_path(url)}); try again later")
        raise OAuthErrorResponse(_error_code(payload), status)

    async def _request(self, method: str, url: str, *, form: Mapping[str, str] | None = None) -> tuple[int, Any]:
        """One request to the tenant: its status and JSON body, or None for an empty or non-JSON body."""
        try:
            async with asyncio.timeout(REQUEST_DEADLINE_SECONDS):
                async with self._http.stream(method, url, data=form) as response:
                    body = await _read_bounded(response)
        except (httpx.TimeoutException, TimeoutError):
            raise NetworkError(f"Auth0 did not answer in time ({_path(url)}); check the connection and try again")
        except httpx.HTTPError:
            raise NetworkError(f"could not reach Auth0 ({_path(url)}); check the connection and try again")
        if response.status_code in _REDIRECT_STATUSES:
            raise ProtocolError(f"Auth0 answered {_path(url)} with a redirect, which the CLI never follows")
        try:
            return response.status_code, json.loads(body) if body else None
        except ValueError:
            return response.status_code, None


def token_failure(exc: OAuthErrorResponse, subject: str) -> CliError:
    """The CliError for an OAuth error answer about `subject` (e.g. "the sign-in code")."""
    if exc.status == 429:
        return NetworkError(f"Auth0 is rate limiting requests for {subject}; wait a minute and try again")
    if exc.error in ("invalid_grant", "access_denied", "expired_token"):
        return AuthError(f"Auth0 rejected {subject} ({exc.error}); nothing was saved, sign in again")
    reason = exc.error or f"HTTP {exc.status}"
    return ProtocolError(
        f"Auth0 refused {subject} ({reason}); check the profile's auth0_client_id and that the application allows"
        " this kind of sign-in"
    )


async def _read_bounded(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise ProtocolError(f"Auth0 sent an unexpectedly large response from {_path(str(response.request.url))}")
        chunks.append(chunk)
    return b"".join(chunks)


def _require_ok(status: int, document: Any, url: str) -> None:
    if status >= 500 or status == 429:
        raise NetworkError(f"Auth0 is unavailable (HTTP {status} from {_path(url)}); try again later")
    if status != 200:
        raise ProtocolError(f"Auth0 answered {_path(url)} with HTTP {status}; check auth0_domain")
    if not isinstance(document, dict):
        raise ProtocolError(f"Auth0 sent a malformed response from {_path(url)}")


def _parse_metadata(document: dict[str, Any], settings: CliSettings) -> ProviderMetadata:
    if document.get("issuer") != settings.issuer:
        raise ProtocolError("the tenant's discovery document names a different issuer; check auth0_domain")
    for field, required in (
        ("code_challenge_methods_supported", "S256"),
        ("id_token_signing_alg_values_supported", "RS256"),
    ):
        advertised = document.get(field)
        if advertised is not None and (not isinstance(advertised, list) or required not in advertised):
            raise ProtocolError(f"the tenant does not support {required} ({field})")
    return ProviderMetadata(
        issuer=settings.issuer,
        authorization_endpoint=_required_tenant_url(document, "authorization_endpoint", settings),
        token_endpoint=_required_tenant_url(document, "token_endpoint", settings),
        jwks_uri=_required_tenant_url(document, "jwks_uri", settings),
        device_authorization_endpoint=_tenant_url(document, "device_authorization_endpoint", settings),
        revocation_endpoint=_tenant_url(document, "revocation_endpoint", settings),
    )


def _tenant_url(document: dict[str, Any], field: str, settings: CliSettings) -> str | None:
    """An endpoint from discovery, accepted only as https on the configured tenant host itself; None when absent."""
    value = document.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.isascii() or any(c.isspace() for c in value):
        raise ProtocolError(f"the tenant's discovery document has a malformed {field}")
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if (
        parts.scheme != "https"
        or parts.hostname != settings.auth0_domain
        or port not in (None, 443)
        or "@" in parts.netloc
        or parts.query
        or parts.fragment
        or not parts.path.startswith("/")
    ):
        raise ProtocolError(f"the tenant's {field} is not an https URL on {settings.auth0_domain}")
    return value


def _required_tenant_url(document: dict[str, Any], field: str, settings: CliSettings) -> str:
    url = _tenant_url(document, field, settings)
    if url is None:
        raise ProtocolError(f"the tenant's discovery document has no {field}")
    return url


def _token_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_TOKEN_CHARS or not value.isascii():
        raise ProtocolError(f"the token response has a missing or malformed {field}")
    return value


def _granted_scopes(value: Any, requested: tuple[str, ...]) -> tuple[str, ...]:
    """RFC 6749 §5.1: an omitted scope means the requested scope was granted unchanged."""
    if value is None:
        granted = requested
    elif isinstance(value, str) and value.strip():
        granted = tuple(dict.fromkeys(value.split()))
    else:
        raise ProtocolError("the token response has a malformed scope")
    if "openid" not in granted:
        raise ProtocolError("the tenant did not grant the openid scope, so the sign-in cannot be verified")
    return granted


def _error_code(payload: Any) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    return error if isinstance(error, str) and _ERROR_CODE.fullmatch(error) else ""


def _path(url: str) -> str:
    return urlsplit(url).path or "/"


_CLOCK_HINT = "check that this computer's clock is correct"


def _jwt_reason(exc: jwt.PyJWTError) -> str:
    match exc:
        case jwt.ExpiredSignatureError():
            return f"it has expired; {_CLOCK_HINT}"
        case jwt.ImmatureSignatureError():
            return f"it is not valid yet; {_CLOCK_HINT}"
        case jwt.InvalidAudienceError():
            return "it was issued for a different audience; check auth0_audience and auth0_client_id"
        case jwt.InvalidIssuerError():
            return "it was issued by a different tenant; check auth0_domain"
        case jwt.InvalidSignatureError():
            return "its signature does not verify"
        case jwt.MissingRequiredClaimError():
            return f"it has no '{exc.claim}' claim" if exc.claim in REQUIRED_CLAIMS else "a required claim is missing"
        case jwt.InvalidAlgorithmError():
            return f"it is not signed with {', '.join(ALGORITHMS)}"
        case _:
            return "it is malformed"


def _oidc_reason(exc: JoseError) -> str:
    claim = getattr(exc, "claim", None)
    if exc.error == "expired_token":
        return f"it has expired; {_CLOCK_HINT}"
    if claim == "iat":
        return f"it was issued in the future; {_CLOCK_HINT}"
    if claim in ("iss", "sub", "aud", "exp", "nbf", "nonce", "azp", "at_hash", "auth_time", "amr"):
        return f"its '{claim}' claim is {'missing' if exc.error == 'missing_claim' else 'invalid'}"
    return "it failed OpenID Connect validation"
