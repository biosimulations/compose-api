"""Device authorization (RFC 8628): sign in on another device, for SSH sessions and hosts without a browser.

The device code stays in memory and is never printed; only the short user code and the tenant's verification page
are shown. Polling follows the server's interval, slows down when asked, backs off on transient failures and stops at
the deadline -- it never starts a new device authorization on its own.
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

from compose_api.cli.auth.models import SIGN_IN_TIMEOUT_SECONDS, Notify, Provider, SignInRequest, TokenGrant
from compose_api.cli.auth.oauth import Auth0OAuthClient, OAuthErrorResponse
from compose_api.cli.config import requested_scopes
from compose_api.cli.errors import AuthError, NetworkError, ProtocolError

DEFAULT_INTERVAL_SECONDS: Final = 5  # RFC 8628 §3.2, when the server names none
SLOW_DOWN_SECONDS: Final = 5  # RFC 8628 §3.5: added to the interval for this and every later poll
MAX_INTERVAL_SECONDS: Final = 60
MAX_EXPIRES_IN_SECONDS: Final = 3600

_USER_CODE = re.compile(r"[A-Za-z0-9-]{1,32}")
_DEVICE_CODE = re.compile(r"[\x21-\x7e]{1,2048}")

type Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class DeviceAuthorization:
    device_code: str = field(repr=False)
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    interval: int


def parse_device_authorization(payload: dict[str, Any], *, tenant_host: str) -> DeviceAuthorization:
    """Validate the device endpoint's answer. Pages are accepted only as https on the configured tenant host, so the
    CLI never shows a link the tenant did not own."""
    device_code = payload.get("device_code")
    if not isinstance(device_code, str) or not _DEVICE_CODE.fullmatch(device_code):
        raise ProtocolError("the device sign-in response has a missing or malformed device_code")
    user_code = payload.get("user_code")
    if not isinstance(user_code, str) or not _USER_CODE.fullmatch(user_code):
        raise ProtocolError("the device sign-in response has a missing or malformed user_code")
    verification_uri = _tenant_page(payload.get("verification_uri"), tenant_host, "verification_uri")
    complete = payload.get("verification_uri_complete")
    if complete is not None:
        complete = _tenant_page(complete, tenant_host, "verification_uri_complete")
        page, filled = urlsplit(verification_uri), urlsplit(complete)
        if (filled.netloc, filled.path) != (page.netloc, page.path) or parse_qs(filled.query).get("user_code") != [
            user_code
        ]:
            raise ProtocolError("the device sign-in response's verification_uri_complete does not match its code")
    expires_in = payload.get("expires_in")
    if type(expires_in) is not int or not 0 < expires_in <= MAX_EXPIRES_IN_SECONDS:
        raise ProtocolError("the device sign-in response has a missing or malformed expires_in")
    interval = payload.get("interval", DEFAULT_INTERVAL_SECONDS)
    if type(interval) is not int or not 0 < interval <= MAX_INTERVAL_SECONDS:
        raise ProtocolError("the device sign-in response has a malformed interval")
    return DeviceAuthorization(
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        verification_uri_complete=complete,
        expires_in=expires_in,
        interval=interval,
    )


async def device_sign_in(
    client: Auth0OAuthClient,
    request: SignInRequest,
    *,
    notify: Notify,
    sleep: Sleep = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    timeout: float = SIGN_IN_TIMEOUT_SECONDS,
) -> TokenGrant:
    scopes = requested_scopes(persistent=request.persistent)
    authorization = parse_device_authorization(
        await client.device_authorization(scopes), tenant_host=client.settings.auth0_domain
    )
    lifetime = min(authorization.expires_in, timeout)
    notify(_instructions(authorization, request.provider, round(lifetime / 60) or 1))
    deadline = monotonic() + lifetime
    interval = float(authorization.interval)
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise AuthError(
                "the sign-in code expired before sign-in finished, so nothing was saved; run the command again"
            )
        await sleep(min(interval, remaining))
        try:
            payload = await client.poll_device_token(authorization.device_code)
        except OAuthErrorResponse as exc:
            interval = _next_interval(exc, interval)
            continue
        except NetworkError:
            interval = min(interval * 2, MAX_INTERVAL_SECONDS)  # transient: back off, still inside the deadline
            continue
        # Auth0 has now spent the device code, so a failure from here on is final: polling again cannot succeed.
        return await client.accept_device_grant(payload, scopes)


def _next_interval(exc: OAuthErrorResponse, interval: float) -> float:
    if exc.error == "authorization_pending":
        return interval
    if exc.error == "slow_down" or exc.status == 429:
        return interval + SLOW_DOWN_SECONDS
    if exc.error == "access_denied":
        raise AuthError("sign-in was refused on the other device; nothing was saved")
    if exc.error == "expired_token":
        raise AuthError("the sign-in code expired before sign-in finished, so nothing was saved; run the command again")
    raise ProtocolError(f"Auth0 stopped the device sign-in ({exc.error or f'HTTP {exc.status}'})")


def _instructions(authorization: DeviceAuthorization, provider: Provider | None, minutes: int) -> str:
    lines = [
        "To sign in, open this page in a browser on any device:",
        "",
        f"  {authorization.verification_uri}",
        "",
        "and enter this code:",
        "",
        f"  {authorization.user_code}",
        "",
    ]
    if authorization.verification_uri_complete is not None:
        lines += [f"(or open {authorization.verification_uri_complete})", ""]
    lines.append("Only enter a code that you just printed yourself; never one someone sent you.")
    if provider is Provider.GOOGLE:
        lines.append("Choose Google on that page: device sign-in cannot pick the provider for you.")
    elif provider is Provider.EMAIL:
        lines.append("Choose email and password on that page: device sign-in cannot pick the provider for you.")
    lines.append(f"Waiting up to {minutes} minutes.")
    return "\n".join(lines)


def _tenant_page(value: Any, tenant_host: str, field: str) -> str:
    if not isinstance(value, str) or not value.isascii() or not value.isprintable() or " " in value:
        raise ProtocolError(f"the device sign-in response has a missing or malformed {field}")
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if (
        parts.scheme != "https"
        or parts.hostname != tenant_host
        or port not in (None, 443)
        or "@" in parts.netloc
        or parts.fragment
    ):
        raise ProtocolError(f"the device sign-in response's {field} is not an https page on {tenant_host}")
    return value
