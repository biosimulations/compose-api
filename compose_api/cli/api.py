"""The CLI's only route to the Compose API. `ComposeApi` owns the bearer token; nothing else sends it anywhere.

Calls go through the generated client's `asyncio_detailed` operations, never hand-written requests or models, on an
httpx client whose policy is spelled out here: TLS verification (with the profile's CA bundle when it has one),
finite timeouts, no redirects, and nothing taken from the environment. A request hook checks each request's exact
scheme, host, port and path before it leaves, so the bearer can only reach this profile's API and the four
operations the CLI uses -- never Auth0, a redirect target or a lookalike host.

Every status is interpreted here before a parsed body is trusted. A read survives one 401 by renewing the session
once and replaying once. A submission is never replayed: once it may have reached the server, a second attempt
could create a second run. Messages name the operation and the status, never a body, a header or a token.
"""

import asyncio
import re
import ssl
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, BinaryIO, Final, Protocol
from urllib.parse import urlsplit

import httpx

from compose_api.api.client import AuthenticatedClient
from compose_api.api.client.api.authentication import get_current_principal
from compose_api.api.client.api.compute import get_simulator_list
from compose_api.api.client.api.results import get_simulation_status
from compose_api.api.client.api.simulation import run_simulation
from compose_api.api.client.models import (
    BodyRunSimulation,
    CurrentPrincipalResponse,
    HpcRun,
    HTTPValidationError,
    RegisteredSimulators,
    SimulationExperiment,
)
from compose_api.api.client.types import File, Response
from compose_api.cli.auth.models import SessionRecord
from compose_api.cli.auth.session import AuthSession, OAuthSessionClient
from compose_api.cli.config import CliSettings
from compose_api.cli.errors import (
    ApiError,
    AuthError,
    CliError,
    ConfigError,
    ForbiddenError,
    InvalidRequestError,
    NetworkError,
    NotFoundError,
    ProtocolError,
    RateLimitedError,
    ServerError,
)

TIMEOUT: Final = httpx.Timeout(60.0, connect=5.0, pool=5.0)  # read and write 60 s
COMMAND_DEADLINE_SECONDS: Final = 90.0
MAX_RETRY_AFTER_SECONDS: Final = 86400
MAX_VALIDATION_FIELDS: Final = 5
_FIELD_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    replayable: bool  # safe to send twice: a read, with no effect on the server

    def __str__(self) -> str:
        return f"{self.method} {self.path}"


CURRENT_PRINCIPAL: Final = Operation("GET", "/auth/me", replayable=True)
SIMULATOR_LIST: Final = Operation("GET", "/core/simulator/list", replayable=True)
SIMULATION_STATUS: Final = Operation("GET", "/results/simulation/status", replayable=True)
RUN_SIMULATION: Final = Operation("POST", "/simulation/run", replayable=False)
ALLOWED_PATHS: Final = frozenset(
    op.path for op in (CURRENT_PRINCIPAL, SIMULATOR_LIST, SIMULATION_STATUS, RUN_SIMULATION)
)

_UNKNOWN_OUTCOME = (
    "The simulation may or may not have been created: do not submit again blindly; check the server's simulations first"
)


class TokenSource(Protocol):
    """Where the bearer comes from: the stored session, or one held in memory for a single command."""

    async def current(self) -> SessionRecord: ...

    async def renew(self, rejected: SessionRecord) -> SessionRecord | None:
        """A successor for a session the API rejected, or None when this source cannot renew."""
        ...

    async def confirmed(self, record: SessionRecord, at: datetime) -> None: ...


class StoredSession:
    """The persistent session. Renewal goes through `AuthSession`, so it is serialized and never replays a token."""

    def __init__(self, session: AuthSession, oauth: OAuthSessionClient) -> None:
        self.session = session
        self.oauth = oauth

    async def current(self) -> SessionRecord:
        return await self.session.get_access_token(self.oauth)

    async def renew(self, rejected: SessionRecord) -> SessionRecord | None:
        if rejected.refresh_token is None:
            return None
        # Forces one renewal, unless another process already replaced the rejected generation.
        return await self.session.get_access_token(self.oauth, rejected_generation=rejected.generation)

    async def confirmed(self, record: SessionRecord, at: datetime) -> None:
        await self.session.mark_verified(record, at)


class OneCommandSession:
    """A `--ephemeral-auth` session: memory only, no refresh token, nothing recorded anywhere."""

    def __init__(self, record: SessionRecord) -> None:
        self.record = record

    async def current(self) -> SessionRecord:
        return self.record

    async def renew(self, rejected: SessionRecord) -> SessionRecord | None:
        return None

    async def confirmed(self, record: SessionRecord, at: datetime) -> None:
        return None


class UnsafeRequestError(Exception):
    """A request was about to leave for somewhere other than this profile's API operations. Never sent."""


@dataclass(frozen=True)
class _Answer:
    status: int
    parsed: Any
    headers: httpx.Headers


_UNREADABLE: Final = object()  # a body the generated model could not parse


class ComposeApi:
    """One profile's API. Each attempt opens its own client and closes it before returning."""

    def __init__(
        self,
        settings: CliSettings,
        tokens: TokenSource,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.tokens = tokens
        self._transport = transport
        origin = urlsplit(settings.api_base_url)
        self._origin = (origin.scheme, origin.hostname, origin.port)
        self._verify = _tls_verification(settings)

    async def verify_identity(self) -> tuple[SessionRecord, CurrentPrincipalResponse]:
        """Ask the API who this session is, and record the answer if it matches the session's own identity."""
        principal, record = await self._call(
            CURRENT_PRINCIPAL,
            lambda client: get_current_principal.asyncio_detailed(client=client),
            CurrentPrincipalResponse,
        )
        if (principal.issuer, principal.subject) != (record.identity.issuer, record.identity.subject):
            raise ProtocolError(
                "the API identifies this session as a different user than the one that signed in; check that"
                " api_base_url, auth0_domain and auth0_audience describe the same deployment"
            )
        await self.tokens.confirmed(record, datetime.now(UTC))
        return record, principal

    async def list_simulators(self) -> RegisteredSimulators:
        simulators, _ = await self._call(
            SIMULATOR_LIST, lambda client: get_simulator_list.asyncio_detailed(client=client), RegisteredSimulators
        )
        return simulators

    async def simulation_status(self, simulation_id: int) -> HpcRun:
        run, _ = await self._call(
            SIMULATION_STATUS,
            lambda client: get_simulation_status.asyncio_detailed(client=client, simulation_id=simulation_id),
            HpcRun,
            not_found=f"there is no simulation {simulation_id} on this server",
        )
        return run

    async def submit_simulation(
        self, archive: BinaryIO, *, file_name: str, interval_time: float | None, batch: bool
    ) -> SimulationExperiment:
        """Upload an OMEX archive once. The caller owns `archive` and closes it."""
        body = BodyRunSimulation(uploaded_file=File(payload=archive, file_name=file_name, mime_type="application/zip"))

        def send(client: AuthenticatedClient) -> Awaitable[Response[Any]]:
            archive.seek(0)
            if interval_time is None:
                return run_simulation.asyncio_detailed(client=client, body=body, batch_submission=batch)
            return run_simulation.asyncio_detailed(
                client=client, body=body, interval_time=interval_time, batch_submission=batch
            )

        experiment, _ = await self._call(RUN_SIMULATION, send, SimulationExperiment)
        return experiment

    async def _call[T](
        self,
        operation: Operation,
        send: Callable[[AuthenticatedClient], Awaitable[Response[Any]]],
        expected: type[T],
        *,
        not_found: str | None = None,
    ) -> tuple[T, SessionRecord]:
        record = await self.tokens.current()
        answer = await self._attempt(operation, record, send)
        if answer.status == 401:
            record, answer = await self._after_unauthorized(operation, record, send)
        if answer.status == 200:
            if isinstance(answer.parsed, expected):
                return answer.parsed, record
            suffix = f" {_UNKNOWN_OUTCOME}." if not operation.replayable else ""
            raise ProtocolError(f"the API's answer to {operation} could not be read.{suffix}")
        raise _failure(operation, answer, not_found=not_found)

    async def _after_unauthorized(
        self,
        operation: Operation,
        rejected: SessionRecord,
        send: Callable[[AuthenticatedClient], Awaitable[Response[Any]]],
    ) -> tuple[SessionRecord, _Answer]:
        """One renewal and, for a read, one replay. A second 401 is final."""
        if not operation.replayable:
            # Renew for the next invocation if that is possible, but never send the submission again. A 401 comes
            # from the authentication check, before the request is handled, so nothing was created.
            renewed: SessionRecord | None = None
            with suppress(CliError):
                renewed = await self.tokens.renew(rejected)
            hint = "the session was renewed, so" if renewed is not None else "sign in again, then"
            raise AuthError(
                f"the API rejected this session's credentials, so the simulation was not submitted; {hint} run the"
                " command again"
            )
        renewed = await self.tokens.renew(rejected)
        if renewed is None:
            raise AuthError(_rejected_message(renewable=False))
        answer = await self._attempt(operation, renewed, send)
        if answer.status == 401:
            raise AuthError(_rejected_message(renewable=True))
        return renewed, answer

    async def _attempt(
        self,
        operation: Operation,
        record: SessionRecord,
        send: Callable[[AuthenticatedClient], Awaitable[Response[Any]]],
    ) -> _Answer:
        """Send once on a fresh client, so a renewed token can never share a client with the one it replaced."""
        received: list[httpx.Response] = []

        async def remember(response: httpx.Response) -> None:
            received.append(response)

        client = AuthenticatedClient(
            base_url=self.settings.api_base_url,
            token=record.access_token.get_secret_value(),
            timeout=TIMEOUT,
            verify_ssl=self._verify,
            follow_redirects=False,
            raise_on_unexpected_status=False,
            httpx_args={
                "trust_env": False,
                "transport": self._transport,
                "event_hooks": {"request": [self._guard], "response": [remember]},
            },
        )
        try:
            async with client, asyncio.timeout(COMMAND_DEADLINE_SECONDS):
                response = await send(client)
            return _Answer(int(response.status_code), response.parsed, httpx.Headers(response.headers))
        except UnsafeRequestError:
            raise ProtocolError(
                f"refused to send credentials for {operation} anywhere but {self.settings.api_base_url}"
            ) from None
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # Nothing reached the server, so even a submission is known not to have happened.
            raise NetworkError(
                f"could not connect to the API at {self.settings.api_base_url}; check the connection and api_base_url"
            ) from None
        except (TimeoutError, httpx.TimeoutException):
            raise NetworkError(_unanswered(operation, "did not answer in time")) from None
        except httpx.HTTPError:
            raise NetworkError(_unanswered(operation, "connection failed before an answer arrived")) from None
        except (ValueError, KeyError, TypeError, AttributeError):
            # The generated model could not parse the body. The status still decides what happened.
            if not received:
                raise ProtocolError(f"the API's answer to {operation} could not be read") from None
            return _Answer(received[-1].status_code, _UNREADABLE, received[-1].headers)

    async def _guard(self, request: httpx.Request) -> None:
        url = request.url
        if (url.scheme, url.host, url.port) != self._origin or url.userinfo or url.path not in ALLOWED_PATHS:
            raise UnsafeRequestError


def _tls_verification(settings: CliSettings) -> ssl.SSLContext | bool:
    """System trust, extended by the profile's CA bundle when it names one. Verification is never switched off."""
    if settings.ca_bundle is None:
        return True
    try:
        return ssl.create_default_context(cafile=str(settings.ca_bundle))
    except (OSError, ssl.SSLError):
        raise ConfigError(f"ca_bundle ({settings.ca_bundle}) is not a readable PEM file of CA certificates") from None


def _rejected_message(*, renewable: bool) -> str:
    detail = "even after renewing the session" if renewable else "and this session cannot be renewed"
    return (
        f"the API rejected this session's credentials {detail}; sign in again. If that keeps happening, check that"
        " the profile's auth0_domain and auth0_audience match the API at api_base_url"
    )


def _unanswered(operation: Operation, what: str) -> str:
    message = f"the API {what} ({operation})"
    return message if operation.replayable else f"{message}. {_UNKNOWN_OUTCOME}"


def _failure(operation: Operation, answer: _Answer, *, not_found: str | None) -> CliError:
    status = answer.status
    unknown = "" if operation.replayable else f" {_UNKNOWN_OUTCOME}."
    if 300 <= status < 400:
        return ProtocolError(
            f"the API answered {operation} with a redirect (HTTP {status}); credentials are never sent to a redirect."
            " Check api_base_url"
        )
    if status == 403:
        return ForbiddenError(
            f"the API refused {operation} for this account (HTTP 403); signing in again will not change that"
        )
    if status == 404:
        return NotFoundError(not_found or f"the API has no {operation} (HTTP 404); check api_base_url")
    if status in (400, 422):
        fields = _invalid_fields(answer.parsed)
        where = f" ({', '.join(fields)})" if fields else ""
        return InvalidRequestError(f"the API rejected the request as invalid{where} (HTTP {status} from {operation})")
    if status == 429:
        wait = _retry_after(answer.headers.get("retry-after"))
        hint = f"retry after {wait} s" if wait is not None else "wait a little and try again"
        return RateLimitedError(f"the API is rate limiting requests (HTTP 429 from {operation}); {hint}")
    if status in (502, 503, 504):
        return NetworkError(f"the API is unavailable (HTTP {status} from {operation}); try again later.{unknown}")
    if status >= 500:
        return ServerError(f"the API failed while handling {operation} (HTTP {status}).{unknown}")
    return ApiError(f"the API answered {operation} with HTTP {status}")


def _invalid_fields(parsed: Any) -> list[str]:
    """Where the API says the request was invalid, as field paths only: never its messages or the input it echoes."""
    if not isinstance(parsed, HTTPValidationError) or not isinstance(parsed.detail, list):
        return []
    fields: list[str] = []
    for item in parsed.detail[:MAX_VALIDATION_FIELDS]:
        parts = [str(part) for part in getattr(item, "loc", [])]
        if parts and all(_FIELD_NAME.fullmatch(part) for part in parts):
            fields.append(".".join(parts))
    return fields


def _retry_after(value: str | None) -> int | None:
    """A Retry-After given in seconds, if it is a sane one. HTTP dates and anything unbounded are not shown."""
    if value is None or not value.strip().isdigit():
        return None
    seconds = int(value.strip())
    return seconds if seconds <= MAX_RETRY_AFTER_SECONDS else None
