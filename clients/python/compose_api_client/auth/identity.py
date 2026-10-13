"""Identity verification (`/auth/me`) and the `ComposeApi` boundary for the CLI's authenticated operations."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, BinaryIO, Protocol, TypeVar

import httpx

from compose_api_client import AuthenticatedClient
from compose_api_client.api.authentication import get_current_principal
from compose_api_client.api.compute import get_simulator_list
from compose_api_client.api.results import get_simulation_status
from compose_api_client.api.simulation import run_simulation
from compose_api_client.auth.models import SessionRecord
from compose_api_client.auth.oauth import Auth0OAuthClient
from compose_api_client.auth.session import AuthSession, AuthStatus
from compose_api_client.auth.sources import OneCommandSession, StoredSession
from compose_api_client.auth.storage import CredentialStore
from compose_api_client.ext._policy import (
    _UNKNOWN_OUTCOME,
    _UNREADABLE,
    ALLOWED_PATHS,
    COMMAND_DEADLINE_SECONDS,
    CURRENT_PRINCIPAL,
    RUN_SIMULATION,
    SIMULATION_STATUS,
    SIMULATOR_LIST,
    TIMEOUT,
    Operation,
    UnsafeRequestError,
    _Answer,
    _DestinationGuard,
    classify_failure,
    rejected_message,
    tls_verification,
    unanswered,
)
from compose_api_client.ext.errors import AuthError, CliError, NetworkError, ProtocolError
from compose_api_client.models import (
    BodyRunSimulation,
    CurrentPrincipalResponse,
    HpcRun,
    RegisteredSimulators,
    SimulationExperiment,
)
from compose_api_client.profiles import CliSettings
from compose_api_client.types import File, Response

T = TypeVar("T")


class RecordTokenSource(Protocol):
    """Where the bearer comes from: the stored session, or one held in memory for a single command."""

    async def current(self) -> SessionRecord: ...

    async def renew(self, rejected: SessionRecord) -> SessionRecord | None:
        """A successor for a session the API rejected, or None when this source cannot renew."""
        ...

    async def confirmed(self, record: SessionRecord, at: datetime) -> None: ...


TokenSource = RecordTokenSource


class ComposeApi:
    """One profile's API. Each attempt opens its own client and closes it before returning."""

    def __init__(
        self,
        settings: CliSettings,
        tokens: RecordTokenSource,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.tokens = tokens
        self._transport = transport
        self._guard_hook = _DestinationGuard(settings.api_base_url, allowed_paths=ALLOWED_PATHS)
        self._origin = self._guard_hook.origin
        self._verify = tls_verification(settings.ca_bundle)

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

    async def _call(
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
        raise classify_failure(operation, answer, not_found=not_found)

    async def _after_unauthorized(
        self,
        operation: Operation,
        rejected: SessionRecord,
        send: Callable[[AuthenticatedClient], Awaitable[Response[Any]]],
    ) -> tuple[SessionRecord, _Answer]:
        """One renewal and, for a read, one replay. A second 401 is final."""
        if not operation.replayable:
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
            raise AuthError(rejected_message(renewable=False))
        answer = await self._attempt(operation, renewed, send)
        if answer.status == 401:
            raise AuthError(rejected_message(renewable=True))
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
            return _Answer(
                int(response.status_code), response.parsed, httpx.Headers(response.headers), response.content
            )
        except UnsafeRequestError:
            raise ProtocolError(
                f"refused to send credentials for {operation} anywhere but {self.settings.api_base_url}"
            ) from None
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise NetworkError(
                f"could not connect to the API at {self.settings.api_base_url}; check the connection and api_base_url"
            ) from None
        except (TimeoutError, httpx.TimeoutException):
            raise NetworkError(unanswered(operation, "did not answer in time")) from None
        except httpx.HTTPError:
            raise NetworkError(unanswered(operation, "connection failed before an answer arrived")) from None
        except (ValueError, KeyError, TypeError, AttributeError):
            if not received:
                raise ProtocolError(f"the API's answer to {operation} could not be read") from None
            return _Answer(received[-1].status_code, _UNREADABLE, received[-1].headers, received[-1].content)

    async def _guard(self, request: httpx.Request) -> None:
        self._guard_hook.check(request)


async def confirm_identity(
    settings: CliSettings,
    store: CredentialStore,
    *,
    auth0_transport: httpx.AsyncBaseTransport | None = None,
    api_transport: httpx.AsyncBaseTransport | None = None,
    after_sign_in: bool,
) -> AuthStatus:
    """Renew if needed, ask the API who this session is, and record the confirmation."""
    session = AuthSession(settings, store)
    try:
        async with Auth0OAuthClient(settings, transport=auth0_transport) as oauth:
            await ComposeApi(settings, StoredSession(session, oauth), transport=api_transport).verify_identity()
    except CliError as exc:
        if after_sign_in:
            raise type(exc)(
                f"signed in and saved the session, but the Compose API did not confirm it: {exc.message}. Run"
                " `compose-api auth status --verify` to check again"
            ) from None
        if isinstance(exc, NetworkError):
            raise type(exc)(
                f"{exc.message}. This is not a sign-out: `compose-api auth status` shows the stored session"
            ) from None
        raise
    return await session.status()


__all__ = [
    "ALLOWED_PATHS",
    "CURRENT_PRINCIPAL",
    "RUN_SIMULATION",
    "SIMULATION_STATUS",
    "SIMULATOR_LIST",
    "ComposeApi",
    "OneCommandSession",
    "StoredSession",
    "TokenSource",
    "UnsafeRequestError",
    "confirm_identity",
]
