"""Sessions over the generated client: submit, status, wait, results, the catalogue.

``ComposeSession`` is synchronous and ``AsyncComposeSession`` asynchronous; they offer the same methods. Both wrap a
generated ``Client`` (or ``AuthenticatedClient`` when given a token/TokenSource) with destination guarding,
``trust_env=False``, redirect refusal, and one-renewal 401 replay for read operations.
"""

from __future__ import annotations

import asyncio
import datetime
import io
import time
import uuid
import zipfile
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import suppress
from http import HTTPStatus
from pathlib import Path
from typing import Any, cast

import httpx
from attrs import define

from compose_api_client import AuthenticatedClient, Client
from compose_api_client.api.authentication import get_current_principal
from compose_api_client.api.biosim_api import check_health_health_get, get_version_version_get
from compose_api_client.api.compute import get_processes_list, get_simulator_list, get_steps_list
from compose_api_client.api.curated import run_copasi, run_tellurium
from compose_api_client.api.datasets import get_dataset, get_dataset_content, get_dataset_file, list_datasets
from compose_api_client.api.registry import (
    build_environment,
    build_simulator,
    create_environment_version,
    export_environment_version,
    get_environment_headers,
    get_environment_images,
    get_environment_manifest,
    get_environment_version,
    get_environment_version_compliance,
    get_simulator_images,
    inspect_environment_version,
    list_environment_versions,
    list_environments,
    list_registry_entries,
    list_solvers,
    retire_environment_version,
    run_environment_version_compliance,
    set_environment_default,
)
from compose_api_client.api.results import (
    get_simulation_events,
    get_simulation_results_file,
    get_simulation_status,
    get_simulation_trace,
    get_simulation_trace_chrome,
    get_simulations_status_batch,
    get_simulator_build_log,
    get_simulator_build_status,
)
from compose_api_client.api.sed_ml import (
    get_comparison,
    get_comparison_series,
    list_comparison_verifications,
    list_comparisons,
    preview_sedml,
    run_sedml,
    verify_comparison,
)
from compose_api_client.api.simulation import run_simulation
from compose_api_client.api.simulations import cancel_simulation, get_simulation, list_simulations
from compose_api_client.api.sources import (
    get_biomodel,
    get_biomodel_omex,
    get_biosimulations_omex,
    get_biosimulations_project,
    get_biosimulations_reference,
    run_biomodel,
    run_biosimulations_project,
    search_biomodels,
    search_biosimulations_projects,
)
from compose_api_client.api.suites import (
    clear_suite_problem,
    edit_suite_problem,
    get_suite_run,
    list_suite_problems,
    list_suite_runs,
    list_suites,
    mark_suite_problem,
    run_suite,
    verify_suite_run,
)
from compose_api_client.ext._policy import (
    _UNKNOWN_OUTCOME,
    _UNREADABLE,
    COMMAND_DEADLINE_SECONDS,
    CURRENT_PRINCIPAL,
    Operation,
    UnsafeRequestError,
    _Answer,
    _DestinationGuard,
    classify_failure,
    rejected_message,
    tls_verification,
    unanswered,
)
from compose_api_client.ext.credentials import (
    TOKEN_ENV_VAR,
    AsyncTokenSource,
    Credential,
    EnvironmentToken,
    StaticToken,
    TokenSource,
)
from compose_api_client.ext.errors import (
    ApiError,
    ApiTimeout,
    AuthError,
    CliError,
    ExitCode,
    NetworkError,
    ProtocolError,
    UncertainOutcomeError,
    detail_of,
    raise_for,
)
from compose_api_client.models import (
    BiGraphProcess,
    BiGraphStep,
    BiomodelHit,
    BiomodelInfo,
    BodyPreviewSedml,
    BodyRunCopasi,
    BodyRunSedml,
    BodyRunSimulation,
    BodyRunTellurium,
    CatalogEntry,
    Comparison,
    ComparisonPage,
    ComparisonSeries,
    ComplianceReport,
    CurrentPrincipalResponse,
    Dataset,
    DatasetPage,
    DefaultVersion,
    EnvironmentExport,
    EnvironmentHeaders,
    EnvironmentSummary,
    EnvironmentVersion,
    EnvironmentVersionDetail,
    EnvironmentVersions,
    HpcRun,
    ImageStatus,
    InterfaceManifest,
    KnownProblem,
    KnownProblemClear,
    KnownProblemEdit,
    KnownProblemMark,
    ListSimulationsStatusType0,
    NewEnvironmentVersion,
    ProjectInfo,
    RegisteredSimulators,
    RunEvent,
    RunEventPage,
    RunTraceTree,
    SedmlPreview,
    SedmlRunResult,
    SimulationCancellation,
    SimulationDetail,
    SimulationExperiment,
    SimulationPage,
    Solver,
    Suite,
    SuiteRunInfo,
    SuiteRunView,
    SuiteVerifyResult,
    Verification,
    VerifyRequest,
    VerifySuiteRunWhich,
)
from compose_api_client.types import UNSET, File, Response

DEFAULT_URL = "https://compose.cam.uchc.edu"
SUBMITTING = "submitting"
TERMINAL = frozenset({"completed", "failed", "cancelled", "timeout", "out_of_memory"})

FileSource = str | Path | bytes


@define(frozen=True)
class JobState:
    """A job's state. ``status`` is compose-api's job status, or ``"submitting"`` while the service answers 404: it
    has accepted the submission but has not yet created the SLURM job (it may still be fetching the image)."""

    status: str
    record: HpcRun | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    @property
    def slurm_job(self) -> int | None:
        return self.record.slurmjobid if self.record else None

    @classmethod
    def of(cls, run: HpcRun) -> JobState:
        return cls(str(run.status) if run.status else "unknown", run)


def _file(source: FileSource, name: str | None = None) -> File:
    if isinstance(source, bytes):
        return File(payload=io.BytesIO(source), file_name=name or "upload")
    path = Path(source)
    return File(payload=io.BytesIO(path.read_bytes()), file_name=name or path.name)


#: What the generated client raises when a body does not match its model (or is not JSON at all).
_READ_FAILURES = (ValueError, KeyError, TypeError, AttributeError)


def _unreadable(answer: httpx.Response) -> Response[Any]:
    """`answer` as a generated `Response` whose body could not be read: its status is still classified, its body is
    never trusted (`_parsed`)."""
    return Response(
        # Generated Response annotates HTTPStatus, but HTTP also permits extension codes (e.g. 599).
        # Preserve the integer so classification does not fail a second time during parse recovery.
        status_code=cast(HTTPStatus, answer.status_code),
        content=answer.content,
        headers=answer.headers,
        parsed=_UNREADABLE,
    )


def _raise_for(response: Response[Any], op: Operation) -> None:
    """Raise `op`'s error for a non-2xx answer (`_policy.classify_failure`): its message names the operation and the
    status, never text from the response. The decoded body stays on `.detail`, for callers that read it (such as
    `BadRequest.violations`)."""
    code = int(response.status_code)
    if 200 <= code < 300:
        return
    error = classify_failure(
        op,
        _Answer(code, response.parsed, httpx.Headers(response.headers)),
        not_found=f"nothing was found at {op} (HTTP 404)",
    )
    if isinstance(error, ApiError):
        error.detail = detail_of(response.content)
    raise error


def _parsed(response: Response[Any], *, op: Operation | None = None) -> Any:
    code = int(response.status_code)
    if 300 <= code < 400:
        label = str(op) if op is not None else "request"
        raise ProtocolError(
            f"the API answered {label} with a redirect (HTTP {code}); credentials are never sent to a redirect."
            " Check api_base_url"
        )
    if code >= 500 and op is not None and not op.replayable:
        raise UncertainOutcomeError(
            f"the API failed while handling {op} (HTTP {code}). {_UNKNOWN_OUTCOME}.",
            exit_code=ExitCode.FAILURE,
        )
    if op is not None:
        _raise_for(response, op)
    else:
        raise_for(response)
    if response.parsed is _UNREADABLE:
        if op is not None and not op.replayable:
            raise UncertainOutcomeError(
                f"the API's answer to {op} could not be read. {_UNKNOWN_OUTCOME}.", exit_code=ExitCode.FAILURE
            )
        raise ProtocolError(f"the API's answer to {op or 'the request'} could not be read")
    if response.parsed is None and op is not None and not op.replayable:
        raise UncertainOutcomeError(
            f"the API's answer to {op} could not be read. {_UNKNOWN_OUTCOME}.",
            exit_code=ExitCode.FAILURE,
        )
    return response.parsed


def _state(response: Response[Any], *, op: Operation | None = None) -> JobState:
    if int(response.status_code) == 404:
        return JobState(SUBMITTING)
    run = _parsed(response, op=op)
    return JobState.of(run)


def _save(content: bytes, sim_id: int, dest: str | Path) -> Path:
    return _save_named(content, f"simulation_{sim_id}_results.zip", dest)


def _save_named(content: bytes, name: str, dest: str | Path) -> Path:
    """Write ``content`` to ``dest``, or to ``dest/name`` when ``dest`` is a directory (existing, or given with a
    trailing slash)."""
    path = Path(dest)
    if path.is_dir() or str(dest).endswith(("/", "\\")):
        path.mkdir(parents=True, exist_ok=True)
        path = path / Path(name).name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _extract(content: bytes, dest: str | Path) -> list[Path]:
    root = Path(dest)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        for n in names:  # refuse paths that would escape dest
            if Path(n).is_absolute() or ".." in Path(n).parts:
                raise ValueError(f"unsafe path in results archive: {n}")
        root.mkdir(parents=True, exist_ok=True)
        zf.extractall(root)
    return [root / n for n in names]


def _read_timeout(timeout: float, *, download: bool = False) -> float:
    """The longest silence allowed between bytes of an answer. A download gets the session's whole timeout (a server
    building a large archive may say nothing for minutes); anything else at most 60 s."""
    return timeout if download else min(timeout, 60.0)


def _refused(op: Operation, credential: Credential | None, base_url: str) -> str:
    """The destination guard stopped a request before it was sent. Credentials are named only when it carried some."""
    what = "credentials for" if credential is not None else "a request for"
    return f"refused to send {what} {op} anywhere but {base_url}"


def _make_client(
    base_url: str,
    token: str | None,
    timeout: float,
    transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None,
    *,
    verify_ssl: Any = True,
    guard: _DestinationGuard | None = None,
    is_async: bool = False,
    on_response: Callable[[httpx.Response], None] | None = None,
) -> Client | AuthenticatedClient:
    hooks: dict[str, Any] = {}
    if guard is not None:
        hooks["request"] = [guard.async_hook if is_async else guard]
    if on_response is not None:
        if is_async:

            async def record(response: httpx.Response) -> None:
                on_response(response)

            hooks["response"] = [record]
        else:
            hooks["response"] = [on_response]
    args: dict[str, Any] = {"trust_env": False}
    if transport is not None:
        args["transport"] = transport
    if hooks:
        args["event_hooks"] = hooks
    t = httpx.Timeout(timeout, connect=5.0, write=60.0, pool=5.0)
    if token:
        return AuthenticatedClient(
            base_url=base_url,
            token=token,
            timeout=t,
            verify_ssl=verify_ssl,
            follow_redirects=False,
            raise_on_unexpected_status=False,
            httpx_args=args,
        )
    return Client(
        base_url=base_url,
        timeout=t,
        verify_ssl=verify_ssl,
        follow_redirects=False,
        raise_on_unexpected_status=False,
        httpx_args=args,
    )


class ComposeSession:
    """Synchronous access to compose-api. A context manager; ``close()`` releases the connection pool."""

    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        *,
        tokens: TokenSource | None = None,
        token: str | None = None,
        timeout: float = 300.0,
        client: Client | AuthenticatedClient | None = None,
        transport: httpx.BaseTransport | None = None,
        ca_bundle: Path | None = None,
        allowed_paths: frozenset[str] | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._transport = transport
        self._verify = tls_verification(ca_bundle)
        self._guard = _DestinationGuard(base_url, allowed_paths=allowed_paths)
        self.tokens: TokenSource | None = tokens if tokens is not None else (StaticToken(token) if token else None)
        self._provided_client = client
        self._answered: list[httpx.Response] = []
        self._active_token: str | None = token
        self.client = client or _make_client(
            base_url,
            token,
            _read_timeout(timeout),
            transport,
            verify_ssl=self._verify,
            guard=self._guard,
            is_async=False,
            on_response=self._answered.append,
        )

    def __enter__(self) -> ComposeSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.client._client is not None:
            self.client._client.close()
            self.client._client = None

    def _prepare_client(self, token: str | None, timeout: float) -> Client | AuthenticatedClient:
        t = httpx.Timeout(timeout, connect=5.0, write=60.0, pool=5.0)
        if token != self._active_token:
            self.close()
            self.client = _make_client(
                self.base_url,
                token,
                timeout,
                self._transport,
                verify_ssl=self._verify,
                guard=self._guard,
                is_async=False,
                on_response=self._answered.append,
            )
            self._active_token = token
        else:
            self.client._timeout = t
            if self.client._client is not None:
                self.client._client.timeout = t
        return self.client

    def _send(
        self,
        op: Operation,
        call: Callable[[Any], Response[Any]],
        *,
        download: bool = False,
    ) -> tuple[Response[Any], Credential | None]:
        if self._provided_client is not None and self.tokens is None:
            return call(self.client), None
        credential = self.tokens.current() if self.tokens is not None else None
        response = self._attempt(op, credential, call, download=download)
        if int(response.status_code) == 401 and self.tokens is not None and credential is not None:
            credential, response = self._after_unauthorized(op, credential, call, download=download)
        return response, credential

    def _after_unauthorized(
        self,
        op: Operation,
        rejected: Credential,
        call: Callable[[Any], Response[Any]],
        *,
        download: bool = False,
    ) -> tuple[Credential, Response[Any]]:
        is_env = isinstance(self.tokens, EnvironmentToken)
        if is_env:
            suffix = "" if op.replayable else "; the submission was not sent"
            raise AuthError(rejected_message(renewable=False, env_var=TOKEN_ENV_VAR) + suffix)
        if not op.replayable:
            renewed: Credential | None = None
            if self.tokens is not None:
                with suppress(CliError):
                    renewed = self.tokens.renew(rejected)
            hint = "the session was renewed, so" if renewed is not None else "sign in again, then"
            raise AuthError(
                f"the API rejected this session's credentials, so the simulation was not submitted; {hint} run the"
                " command again"
            )
        renewed = self.tokens.renew(rejected) if self.tokens is not None else None
        if renewed is None:
            raise AuthError(rejected_message(renewable=False, env_var=TOKEN_ENV_VAR if is_env else None))
        response = self._attempt(op, renewed, call, download=download)
        if int(response.status_code) == 401:
            raise AuthError(rejected_message(renewable=True))
        return renewed, response

    def _attempt(
        self,
        op: Operation,
        credential: Credential | None,
        call: Callable[[Any], Response[Any]],
        *,
        download: bool = False,
    ) -> Response[Any]:
        self._answered.clear()
        token = credential.access_token if credential is not None else None
        client = self._prepare_client(token, _read_timeout(self.timeout, download=download))
        try:
            return call(client)
        except _READ_FAILURES:
            if not self._answered:
                raise  # nothing came back: a bug, not an answer
            return _unreadable(self._answered[-1])
        except UnsafeRequestError:
            raise ProtocolError(_refused(op, credential, self.base_url)) from None
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise NetworkError(
                f"cannot reach {self.base_url}: could not connect to the API at {self.base_url}; check the connection"
                " and api_base_url; the request is known not sent"
            ) from None
        except (TimeoutError, httpx.TimeoutException):
            if not op.replayable:
                raise UncertainOutcomeError(
                    unanswered(op, "did not answer in time"), exit_code=ExitCode.NETWORK
                ) from None
            raise NetworkError(unanswered(op, "did not answer in time")) from None
        except httpx.HTTPError:
            if not op.replayable:
                raise UncertainOutcomeError(
                    unanswered(op, "connection failed before an answer arrived"), exit_code=ExitCode.NETWORK
                ) from None
            raise NetworkError(unanswered(op, "connection failed before an answer arrived")) from None

    # -- service ----------------------------------------------------------------------------------------------------

    def whoami(self) -> CurrentPrincipalResponse:
        """The identity the service sees for this session's bearer token (GET /auth/me)."""
        r, credential = self._send(
            CURRENT_PRINCIPAL,
            lambda c: get_current_principal.sync_detailed(client=cast(AuthenticatedClient, c)),
        )
        principal: CurrentPrincipalResponse = _parsed(r, op=CURRENT_PRINCIPAL)
        if (
            credential is not None
            and credential.issuer is not None
            and credential.subject is not None
            and (principal.issuer, principal.subject) != (credential.issuer, credential.subject)
        ):
            raise ProtocolError(
                "the API identifies this session as a different user than the one that signed in; check that"
                " api_base_url, auth0_domain and auth0_audience describe the same deployment"
            )
        if self.tokens is not None and credential is not None:
            self.tokens.confirmed(credential, datetime.datetime.now(datetime.UTC))
        return principal

    def health(self) -> dict[str, str]:
        op = Operation("GET", "/health", replayable=True)
        r, _ = self._send(op, lambda c: check_health_health_get.sync_detailed(client=c))
        return dict(_parsed(r, op=op).to_dict())

    def version(self) -> str:
        op = Operation("GET", "/version", replayable=True)
        r, _ = self._send(op, lambda c: get_version_version_get.sync_detailed(client=c))
        return str(_parsed(r, op=op))

    def simulators(self) -> RegisteredSimulators:
        op = Operation("GET", "/core/simulator/list", replayable=True)
        r, _ = self._send(op, lambda c: get_simulator_list.sync_detailed(client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def processes(self) -> list[BiGraphProcess]:
        op = Operation("GET", "/core/processes/list", replayable=True)
        r, _ = self._send(op, lambda c: get_processes_list.sync_detailed(client=c))
        return list(_parsed(r, op=op))

    def steps(self) -> list[BiGraphStep]:
        op = Operation("GET", "/core/steps/list", replayable=True)
        r, _ = self._send(op, lambda c: get_steps_list.sync_detailed(client=c))
        return list(_parsed(r, op=op))

    def environments(self) -> list[EnvironmentSummary]:
        """The environments documents run in, with what their interface manifests hold."""
        op = Operation("GET", "/registry/environments", replayable=True)
        r, _ = self._send(op, lambda c: list_environments.sync_detailed(client=c))
        return list(_parsed(r, op=op))

    def catalog(self) -> list[CatalogEntry]:
        """Every registry entry with its curation level and the environments that provide its classes."""
        op = Operation("GET", "/registry/entries", replayable=True)
        r, _ = self._send(op, lambda c: list_registry_entries.sync_detailed(client=c))
        return list(_parsed(r, op=op))

    def solvers(self) -> list[Solver]:
        """The solvers SED-ML runs can use: class, environment, KiSAO algorithms, what each returns."""
        op = Operation("GET", "/registry/solvers", replayable=True)
        r, _ = self._send(op, lambda c: list_solvers.sync_detailed(client=c))
        return list(_parsed(r, op=op))

    def environment_manifest(self, name: str) -> InterfaceManifest:
        """An environment's interface manifest (pbg-interfaces/1)."""
        op = Operation("GET", f"/registry/environments/{name}/manifest", replayable=True)
        r, _ = self._send(op, lambda c: get_environment_manifest.sync_detailed(name, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def environment_headers(self, name: str) -> EnvironmentHeaders:
        """An environment's interfaces as .pblang header files, and each class's declaration."""
        op = Operation("GET", f"/registry/environments/{name}/headers", replayable=True)
        r, _ = self._send(op, lambda c: get_environment_headers.sync_detailed(name, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def environment_images(self, name: str) -> ImageStatus:
        """Whether an environment's current image is built, with its image records and newest build run."""
        op = Operation("GET", f"/registry/environments/{name}/images", replayable=True)
        r, _ = self._send(op, lambda c: get_environment_images.sync_detailed(name, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def build_environment(self, name: str) -> ImageStatus:
        """Make an environment's current image available: pulled or built unless it is, joining a build under way."""
        op = Operation("POST", f"/registry/environments/{name}/build", replayable=False)
        r, _ = self._send(op, lambda c: build_environment.sync_detailed(name, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def environment_versions(self, name: str) -> EnvironmentVersions:
        """An environment's versions, newest first, and its default (docs/plan-environment-versions.md)."""
        op = Operation("GET", f"/registry/environments/{name}/versions", replayable=True)
        r, _ = self._send(op, lambda c: list_environment_versions.sync_detailed(name, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def environment_version(self, name: str, number: int) -> EnvironmentVersionDetail:
        """One version: what it was made from, its lock, and what it installed and provides."""
        op = Operation("GET", f"/registry/environments/{name}/versions/{number}", replayable=True)
        r, _ = self._send(op, lambda c: get_environment_version.sync_detailed(name, number, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def export_environment_version(self, name: str, number: int, *, format: str | None = None) -> EnvironmentExport:  # noqa: A002
        """The files that recreate a version locally: pixi.toml and pixi.lock, or a uv requirements lock."""
        op = Operation("GET", f"/registry/environments/{name}/versions/{number}/export", replayable=True)
        fmt = format if format is not None else UNSET
        r, _ = self._send(op, lambda c: export_environment_version.sync_detailed(name, number, client=c, format_=fmt))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def environment_compliance(self, name: str, number: int) -> ComplianceReport:
        """Where each entry of a version stands there (its cases' runs), and the components a generic check refuses."""
        op = Operation("GET", f"/registry/environments/{name}/versions/{number}/compliance", replayable=True)
        r, _ = self._send(op, lambda c: get_environment_version_compliance.sync_detailed(name, number, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def run_environment_compliance(self, name: str, number: int) -> ComplianceReport:
        """Run a version's compliance cases again (new runs: sent once, never retried). Needs the environment
        administrator role."""
        op = Operation("POST", f"/registry/environments/{name}/versions/{number}/compliance", replayable=False)
        r, _ = self._send(op, lambda c: run_environment_version_compliance.sync_detailed(name, number, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def create_environment_version(
        self,
        name: str,
        *,
        resolved_at: datetime.datetime | None = None,
        image: str | None = None,
        note: str | None = None,
    ) -> EnvironmentVersion:
        """A new version (or the existing one with the same definition): a shared environment resolved at
        ``resolved_at`` (default now), or a prebuilt one's ``image`` by digest. Its image is built in the background;
        it does not become the default. Needs the environment administrator role."""
        op = Operation("POST", f"/registry/environments/{name}/versions", replayable=False)
        body = NewEnvironmentVersion(
            resolved_at=resolved_at if resolved_at is not None else UNSET,
            image=image if image is not None else UNSET,
            note=note if note is not None else UNSET,
        )
        r, _ = self._send(op, lambda c: create_environment_version.sync_detailed(name, client=c, body=body))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def set_environment_default(self, name: str, number: int) -> EnvironmentVersion:
        """Make a ready version the one runs get when they name none. Needs the environment administrator role."""
        op = Operation("PUT", f"/registry/environments/{name}/default", replayable=True)
        body = DefaultVersion(number=number)
        r, _ = self._send(op, lambda c: set_environment_default.sync_detailed(name, client=c, body=body))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def retire_environment_version(self, name: str, number: int) -> EnvironmentVersion:
        """Retire a version: it refuses new runs; its images are kept. Needs the environment administrator role."""
        op = Operation("POST", f"/registry/environments/{name}/versions/{number}/retire", replayable=True)
        r, _ = self._send(op, lambda c: retire_environment_version.sync_detailed(name, number, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def inspect_environment_version(self, name: str, number: int) -> EnvironmentVersion:
        """Read a prebuilt version's image back again (what it installed and provides), in the background. Needs the
        environment administrator role."""
        op = Operation("POST", f"/registry/environments/{name}/versions/{number}/inspect", replayable=True)
        r, _ = self._send(op, lambda c: inspect_environment_version.sync_detailed(name, number, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def simulator_images(self, simulator_id: int) -> ImageStatus:
        """Whether a simulator's image is built, with its image records and newest build run."""
        op = Operation("GET", f"/registry/simulators/{simulator_id}/images", replayable=True)
        r, _ = self._send(op, lambda c: get_simulator_images.sync_detailed(simulator_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def build_simulator(self, simulator_id: int) -> ImageStatus:
        """Make a simulator's image available: pulled or built unless it is, joining a build under way."""
        op = Operation("POST", f"/registry/simulators/{simulator_id}/build", replayable=False)
        r, _ = self._send(op, lambda c: build_simulator.sync_detailed(simulator_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    # -- submit -----------------------------------------------------------------------------------------------------

    def submit(
        self,
        document: FileSource,
        *,
        simulator: str | None = None,
        interval: float = 1.0,
        batch: bool = False,
        tags: Sequence[str] = (),
        description: str | None = None,
        environment_version: int | None = None,
        environment: str | None = None,
    ) -> SimulationExperiment:
        """Submit an ``.omex`` (or ``.pbg``). ``environment`` names the environment to run in (``simulator`` is the
        older name for a prebuilt one); with neither, the service infers it from the document's classes.
        ``environment_version`` is a version of that environment (its default when omitted); ``tags`` and
        ``description`` are stored with the run and filter ``simulations()``."""
        op = Operation("POST", "/simulation/run", replayable=False)
        r, _ = self._send(
            op,
            lambda c: run_simulation.sync_detailed(
                client=c,
                body=BodyRunSimulation(uploaded_file=_file(document)),
                interval_time=interval,
                batch_submission=batch,
                simulator=simulator if simulator is not None else UNSET,
                tags=list(tags) if tags else UNSET,
                description=description if description is not None else UNSET,
                environment_version=environment_version if environment_version is not None else UNSET,
                environment=environment if environment is not None else UNSET,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def submit_copasi(self, sbml: FileSource, *, start: float, duration: float, points: int) -> SimulationExperiment:
        op = Operation("POST", "/curated/copasi", replayable=False)
        r, _ = self._send(
            op,
            lambda c: run_copasi.sync_detailed(
                client=c,
                body=BodyRunCopasi(sbml=_file(sbml)),
                start_time=start,
                duration=duration,
                num_data_points=points,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def submit_tellurium(self, sbml: FileSource, *, start: float, end: float, points: int) -> SimulationExperiment:
        op = Operation("POST", "/curated/tellurium", replayable=False)
        r, _ = self._send(
            op,
            lambda c: run_tellurium.sync_detailed(
                client=c,
                body=BodyRunTellurium(sbml=_file(sbml)),
                start_time=start,
                end_time=end,
                num_data_points=points,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    # -- status and waiting ---------------------------------------------------------------------------------------

    def status(self, simulation_id: int) -> JobState:
        op = Operation("GET", "/results/simulation/status", replayable=True)
        r, _ = self._send(op, lambda c: get_simulation_status.sync_detailed(client=c, simulation_id=simulation_id))
        return _state(r, op=op)

    def statuses(self, simulation_ids: Sequence[int]) -> list[HpcRun]:
        """Several simulations' job records in one call (only those with a SLURM job yet)."""
        op = Operation("GET", "/results/simulations/status/batch", replayable=True)
        r, _ = self._send(op, lambda c: get_simulations_status_batch.sync_detailed(client=c, body=list(simulation_ids)))
        return list(_parsed(r, op=op))

    def build_log(self, simulator_id: int) -> str:
        """The SLURM log of the simulator's newest container build (its last 200 KB)."""
        op = Operation("GET", "/results/simulator/build/log", replayable=True)
        r, _ = self._send(op, lambda c: get_simulator_build_log.sync_detailed(client=c, simulator_id=simulator_id))
        _raise_for(r, op)
        return r.content.decode(errors="replace")

    def build_status(self, simulator_id: int) -> JobState:
        op = Operation("GET", "/results/simulator/build/status", replayable=True)
        r, _ = self._send(op, lambda c: get_simulator_build_status.sync_detailed(client=c, simulator_id=simulator_id))
        return _state(r, op=op)

    def wait(
        self,
        simulation_id: int,
        *,
        poll: float = 5.0,
        timeout: float | None = None,
        on_update: Callable[[JobState], None] | None = None,
    ) -> JobState:
        """Poll until the job is terminal; the final state. ``on_update`` sees each change of state."""
        return _wait_sync(lambda: self.status(simulation_id), poll, timeout, on_update)

    def wait_build(
        self,
        simulator_id: int,
        *,
        poll: float = 5.0,
        timeout: float | None = None,
        on_update: Callable[[JobState], None] | None = None,
    ) -> JobState:
        return _wait_sync(lambda: self.build_status(simulator_id), poll, timeout, on_update)

    # -- finding simulations ----------------------------------------------------------------------------------------

    def simulations(
        self,
        *,
        status: str | None = None,
        simulator: str | None = None,
        since: datetime.datetime | None = None,
        labels: dict[str, str] | None = None,
        tags: Sequence[str] = (),
        limit: int = 50,
        offset: int = 0,
    ) -> SimulationPage:
        """Simulations the caller may read, newest first, each with its latest SLURM job. ``status`` is a job state
        or ``"submitting"``; ``simulator`` a prebuilt simulator's name or a container-definition hash prefix."""
        op = Operation("GET", "/simulations", replayable=True)
        r, _ = self._send(
            op,
            lambda c: list_simulations.sync_detailed(
                client=c, **_simulation_filters(status, simulator, since, labels, tags, limit, offset)
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    # -- SED-ML -----------------------------------------------------------------------------------------------------

    def sedml_preview(self, archive: FileSource, *, solvers: Sequence[str] = ()) -> SedmlPreview:
        """Translate a SED-ML archive without running it: its tasks, and what each solver would run or why not."""
        op = Operation("POST", "/sedml/preview", replayable=True)
        r, _ = self._send(
            op,
            lambda c: preview_sedml.sync_detailed(
                client=c,
                body=BodyPreviewSedml(archive=_file(archive)),
                solvers=list(solvers) if solvers else UNSET,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def sedml_run(
        self,
        archive: FileSource,
        *,
        solvers: Sequence[str] = (),
        tasks: Sequence[str] = (),
        tags: Sequence[str] = (),
        description: str | None = None,
        environment_versions: Sequence[str] = (),
    ) -> SedmlRunResult:
        """Run each task of a SED-ML archive once per solver; one comparison per task. ``environment_versions``:
        ``environment@number`` or ``environment@default``; an environment not named runs at its default."""
        op = Operation("POST", "/sedml/run", replayable=False)
        r, _ = self._send(
            op,
            lambda c: run_sedml.sync_detailed(
                client=c,
                body=BodyRunSedml(archive=_file(archive)),
                solvers=list(solvers) if solvers else UNSET,
                task=list(tasks) if tasks else UNSET,
                tags=list(tags) if tags else UNSET,
                description=description if description is not None else UNSET,
                environment_version=list(environment_versions) if environment_versions else UNSET,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    # -- sources (BioModels, biosimulations.org) --------------------------------------------------------------------

    def biomodels_search(self, query: str, *, limit: int = 20, curated: bool = True) -> list[BiomodelHit]:
        op = Operation("GET", "/sources/biomodels/search", replayable=True)
        r, _ = self._send(op, lambda c: search_biomodels.sync_detailed(client=c, q=query, limit=limit, curated=curated))
        return list(_parsed(r, op=op))

    def biomodel(self, model_id: str) -> BiomodelInfo:
        op = Operation("GET", f"/sources/biomodels/{model_id}", replayable=True)
        r, _ = self._send(op, lambda c: get_biomodel.sync_detailed(model_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def biomodel_omex(self, model_id: str) -> bytes:
        op = Operation("GET", f"/sources/biomodels/{model_id}/omex", replayable=True)
        r, _ = self._send(op, lambda c: get_biomodel_omex.sync_detailed(model_id, client=c), download=True)
        _raise_for(r, op)
        return r.content

    def run_biomodel(
        self,
        model_id: str,
        *,
        solvers: Sequence[str] = (),
        tags: Sequence[str] = (),
        environment_versions: Sequence[str] = (),
    ) -> SedmlRunResult:
        op = Operation("POST", f"/sources/biomodels/{model_id}/run", replayable=False)
        r, _ = self._send(
            op,
            lambda c: run_biomodel.sync_detailed(
                model_id,
                client=c,
                solvers=list(solvers) if solvers else UNSET,
                tags=list(tags) if tags else UNSET,
                environment_version=list(environment_versions) if environment_versions else UNSET,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def biosimulations_search(self, query: str = "", *, limit: int = 20) -> list[ProjectInfo]:
        op = Operation("GET", "/sources/biosimulations/projects", replayable=True)
        r, _ = self._send(op, lambda c: search_biosimulations_projects.sync_detailed(client=c, q=query, limit=limit))
        return list(_parsed(r, op=op))

    def biosimulations_project(self, project_id: str) -> ProjectInfo:
        op = Operation("GET", f"/sources/biosimulations/{project_id}", replayable=True)
        r, _ = self._send(op, lambda c: get_biosimulations_project.sync_detailed(project_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def biosimulations_omex(self, project_id: str) -> bytes:
        op = Operation("GET", f"/sources/biosimulations/{project_id}/omex", replayable=True)
        r, _ = self._send(op, lambda c: get_biosimulations_omex.sync_detailed(project_id, client=c), download=True)
        _raise_for(r, op)
        return r.content

    def biosimulations_reference(self, project_id: str) -> dict[str, dict[str, list[float]]]:
        """The project's original results: `{"<sedml>/<report>": {label: values}}`."""
        op = Operation("GET", f"/sources/biosimulations/{project_id}/reference", replayable=True)
        r, _ = self._send(op, lambda c: get_biosimulations_reference.sync_detailed(project_id, client=c))
        _raise_for(r, op)
        data: dict[str, dict[str, list[float]]] = r.parsed.to_dict()  # type: ignore[union-attr]
        return data

    def run_biosimulations_project(
        self,
        project_id: str,
        *,
        solvers: Sequence[str] = (),
        tags: Sequence[str] = (),
        environment_versions: Sequence[str] = (),
    ) -> SedmlRunResult:
        op = Operation("POST", f"/sources/biosimulations/{project_id}/run", replayable=False)
        r, _ = self._send(
            op,
            lambda c: run_biosimulations_project.sync_detailed(
                project_id,
                client=c,
                solvers=list(solvers) if solvers else UNSET,
                tags=list(tags) if tags else UNSET,
                environment_version=list(environment_versions) if environment_versions else UNSET,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    # -- suites -----------------------------------------------------------------------------------------------------

    def suites(self) -> list[Suite]:
        op = Operation("GET", "/suites", replayable=True)
        r, _ = self._send(op, lambda c: list_suites.sync_detailed(client=c))
        return list(_parsed(r, op=op))

    def suite_runs(self, name: str) -> list[SuiteRunInfo]:
        op = Operation("GET", f"/suites/{name}/runs", replayable=True)
        r, _ = self._send(op, lambda c: list_suite_runs.sync_detailed(name, client=c))
        return list(_parsed(r, op=op))

    def suite_run(self, name: str, number: int) -> SuiteRunView:
        """One suite run: per source, agreement, references, and drift from the baseline run."""
        op = Operation("GET", f"/suites/{name}/runs/{number}", replayable=True)
        r, _ = self._send(op, lambda c: get_suite_run.sync_detailed(name, number, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def run_suite(self, name: str, *, environment_versions: Sequence[str]) -> SuiteRunInfo:
        """Run every source of the suite (submitted in the background) in the environment versions named:
        ``environment@number``, ``environment@default``, or ``default`` (each at its default); the new run's number."""
        op = Operation("POST", f"/suites/{name}/run", replayable=False)
        r, _ = self._send(
            op, lambda c: run_suite.sync_detailed(name, client=c, environment_version=list(environment_versions))
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def comparisons(self, *, source: str | None = None, limit: int = 25, offset: int = 0) -> ComparisonPage:
        op = Operation("GET", "/comparisons", replayable=True)
        r, _ = self._send(
            op,
            lambda c: list_comparisons.sync_detailed(
                client=c, source=source if source is not None else UNSET, limit=limit, offset=offset
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def comparison_series(self, comparison_id: int, report: str) -> ComparisonSeries:
        """One report's columns from each run and each reference."""
        op = Operation("GET", f"/comparisons/{comparison_id}/series", replayable=True)
        r, _ = self._send(op, lambda c: get_comparison_series.sync_detailed(comparison_id, client=c, report=report))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def comparison(self, comparison_id: int) -> Comparison:
        """One comparison: its runs, and per report and data set each solver pair's score once all have finished."""
        op = Operation("GET", f"/comparisons/{comparison_id}", replayable=True)
        r, _ = self._send(op, lambda c: get_comparison.sync_detailed(comparison_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def verify_comparison(self, comparison_id: int, simulators: list[str] | None = None) -> Verification:
        """Queue a check of the comparison against BioSimulators' simulators (biosim's /verify); one already queued
        or running for the same simulators is returned instead."""
        op = Operation("POST", f"/comparisons/{comparison_id}/verify", replayable=False)
        body = VerifyRequest(simulators=simulators) if simulators else None  # no body: the service's default
        r, _ = self._send(op, lambda c: verify_comparison.sync_detailed(comparison_id, client=c, body=body))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def comparison_verifications(self, comparison_id: int) -> list[Verification]:
        """The comparison's verifications, oldest first."""
        op = Operation("GET", f"/comparisons/{comparison_id}/verifications", replayable=True)
        r, _ = self._send(op, lambda c: list_comparison_verifications.sync_detailed(comparison_id, client=c))
        return list(_parsed(r, op=op))

    def verify_suite_run(self, name: str, number: int, *, which: str = "failing") -> SuiteVerifyResult:
        """Queue verifications for a suite run's finished comparisons: ``failing`` ones, or ``all``."""
        op = Operation("POST", f"/suites/{name}/runs/{number}/verify", replayable=False)
        r, _ = self._send(
            op, lambda c: verify_suite_run.sync_detailed(name, number, client=c, which=VerifySuiteRunWhich(which))
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def suite_problems(self, name: str, *, cleared: bool | None = None) -> list[KnownProblem]:
        """A suite's known problems, oldest first: every one, or only the cleared (True) or open (False) ones."""
        op = Operation("GET", f"/suites/{name}/problems", replayable=True)
        flag = cleared if cleared is not None else UNSET
        r, _ = self._send(op, lambda c: list_suite_problems.sync_detailed(name, client=c, cleared=flag))
        return list(_parsed(r, op=op))

    def mark_suite_problem(
        self,
        name: str,
        source: str,
        *,
        category: str,
        reason: str,
        solver: str | None = None,
        seen_run: int | None = None,
    ) -> KnownProblem:
        """Record a known problem of a solver (or of every solver) on a suite's source (sent once, never retried).
        Needs the suite curator role."""
        op = Operation("POST", f"/suites/{name}/problems", replayable=False)
        mark = KnownProblemMark(
            source=source,
            category=category,
            reason=reason,
            solver=solver if solver is not None else UNSET,
            seen_run=seen_run if seen_run is not None else UNSET,
        )
        r, _ = self._send(op, lambda c: mark_suite_problem.sync_detailed(name, client=c, body=mark))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def edit_suite_problem(
        self, name: str, problem_id: int, *, category: str | None = None, reason: str | None = None
    ) -> KnownProblem:
        """Change a known problem's category or reason. Needs the suite curator role."""
        op = Operation("PATCH", f"/suites/{name}/problems/{problem_id}", replayable=True)
        edit = KnownProblemEdit(
            category=category if category is not None else UNSET, reason=reason if reason is not None else UNSET
        )
        r, _ = self._send(op, lambda c: edit_suite_problem.sync_detailed(name, problem_id, client=c, body=edit))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def clear_suite_problem(self, name: str, problem_id: int, run: int) -> KnownProblem:
        """Clear a known problem at the suite run that shows it fixed. Needs the suite curator role."""
        op = Operation("POST", f"/suites/{name}/problems/{problem_id}/clear", replayable=True)
        body = KnownProblemClear(run=run)
        r, _ = self._send(op, lambda c: clear_suite_problem.sync_detailed(name, problem_id, client=c, body=body))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def simulation(self, simulation_id: int) -> SimulationDetail:
        """One simulation: its latest SLURM job and how many events and datasets its run recorded."""
        op = Operation("GET", f"/simulations/{simulation_id}", replayable=True)
        r, _ = self._send(op, lambda c: get_simulation.sync_detailed(simulation_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def cancel_simulation(self, simulation_id: int) -> SimulationCancellation:
        """Cancel a run (needs a signed-in session): withdrawn from the queue, or SLURM asked to cancel its job."""
        op = Operation("DELETE", f"/simulations/{simulation_id}", replayable=False)
        r, _ = self._send(op, lambda c: cancel_simulation.sync_detailed(simulation_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    # -- events and traces ----------------------------------------------------------------------------------------

    def events(
        self,
        simulation_id: int,
        *,
        after: int | None = None,
        limit: int = 500,
        level: str | None = None,
        event: str | None = None,
        span_id: str | None = None,
    ) -> RunEventPage:
        """A page of the run's events, in the order they were recorded. Pass ``page.next_cursor`` as ``after`` for the
        next page."""
        op = Operation("GET", "/results/simulation/events", replayable=True)
        r, _ = self._send(
            op,
            lambda c: get_simulation_events.sync_detailed(
                client=c, simulation_id=simulation_id, **_event_filters(after, limit, level, event, span_id)
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def iter_events(
        self,
        simulation_id: int,
        *,
        follow: bool = False,
        poll: float = 5.0,
        level: str | None = None,
        event: str | None = None,
    ) -> Iterator[RunEvent]:
        """Every event, page by page. ``follow``: keep polling for new ones until the job is terminal and a poll
        brings nothing new (the service keeps reading a run's last events for a while after it ends)."""
        after: int | None = None
        while True:
            page = self.events(simulation_id, after=after, level=level, event=event)
            yield from page.events
            if page.events:
                after = page.events[-1].cursor if isinstance(page.events[-1].cursor, int) else after
            if page.next_cursor is not None:
                continue
            if not follow or (not page.events and self.status(simulation_id).terminal):
                return
            time.sleep(poll)

    def trace(self, simulation_id: int) -> RunTraceTree:
        """The run's spans as a tree, each span with its own events."""
        op = Operation("GET", "/results/simulation/trace", replayable=True)
        r, _ = self._send(op, lambda c: get_simulation_trace.sync_detailed(client=c, simulation_id=simulation_id))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def trace_chrome(self, simulation_id: int) -> dict[str, Any]:
        """The run's trace as a Chrome Trace Event document: save it as JSON and open it in ui.perfetto.dev."""
        op = Operation("GET", "/results/simulation/trace/chrome", replayable=True)
        r, _ = self._send(
            op, lambda c: get_simulation_trace_chrome.sync_detailed(client=c, simulation_id=simulation_id)
        )
        return dict(_parsed(r, op=op).to_dict())

    # -- datasets ---------------------------------------------------------------------------------------------------

    def datasets(
        self,
        *,
        simulation_id: int | None = None,
        kind: str | None = None,
        q: str | None = None,
        available: bool | None = True,
        limit: int = 100,
        offset: int = 0,
    ) -> DatasetPage:
        """The files runs advertised: one simulation's, or all those the caller may read. ``page.next_offset`` pages."""
        op = Operation("GET", "/datasets", replayable=True)
        r, _ = self._send(
            op,
            lambda c: list_datasets.sync_detailed(
                client=c, **_dataset_filters(simulation_id, kind, q, available, limit, offset)
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def dataset(self, dataset_id: str | uuid.UUID) -> Dataset:
        op = Operation("GET", f"/datasets/{dataset_id}", replayable=True)
        r, _ = self._send(op, lambda c: get_dataset.sync_detailed(uuid.UUID(str(dataset_id)), client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    def dataset_content(self, dataset_id: str | uuid.UUID) -> bytes:
        op = Operation("GET", f"/datasets/{dataset_id}/content", replayable=True)
        r, _ = self._send(
            op, lambda c: get_dataset_content.sync_detailed(uuid.UUID(str(dataset_id)), client=c), download=True
        )
        _raise_for(r, op)
        return r.content

    def dataset_file(self, dataset_id: str | uuid.UUID, subpath: str) -> bytes:
        """One file inside a directory dataset (a ``*.fenics`` results bundle or a ``*.zarr`` store), e.g.
        ``.zattrs`` or a chunk such as ``u/0.0``."""
        op = Operation("GET", f"/datasets/{dataset_id}/files/{subpath}", replayable=True)
        r, _ = self._send(
            op,
            lambda c: get_dataset_file.sync_detailed(uuid.UUID(str(dataset_id)), subpath, client=c),
            download=True,
        )
        _raise_for(r, op)
        return r.content

    def download_dataset_file(self, dataset_id: str | uuid.UUID, subpath: str, dest: str | Path) -> Path:
        """Save one file of a directory dataset to ``dest``: a file, or a directory for the file's own name."""
        return _save_named(self.dataset_file(dataset_id, subpath), subpath, dest)

    def download_dataset(self, dataset_id: str | uuid.UUID, dest: str | Path) -> Path:
        """Save a dataset's file to ``dest``: a file, or a directory (existing, or written with a trailing slash) for
        the file's own name. The path written."""
        info = self.dataset(dataset_id)
        return _save_named(self.dataset_content(dataset_id), Path(info.path).name, dest)

    # -- results ----------------------------------------------------------------------------------------------------

    def results(self, simulation_id: int) -> bytes:
        """The results archive (zip). :class:`NotFound` until the simulation has finished."""
        op = Operation("GET", "/results/simulation/results/file", replayable=True)
        r, _ = self._send(
            op,
            lambda c: get_simulation_results_file.sync_detailed(client=c, simulation_id=simulation_id),
            download=True,
        )
        _raise_for(r, op)
        return r.content

    def download(self, simulation_id: int, dest: str | Path) -> Path:
        """Save the archive to ``dest``: a file, or a directory (existing, or written with a trailing slash) for
        ``simulation_<id>_results.zip``. The path written."""
        return _save(self.results(simulation_id), simulation_id, dest)

    def extract(self, simulation_id: int, dest: str | Path) -> list[Path]:
        """Unpack the archive into the directory ``dest``; the files written."""
        return _extract(self.results(simulation_id), dest)

    def run_and_wait(
        self,
        document: FileSource,
        *,
        simulator: str | None = None,
        interval: float = 1.0,
        poll: float = 5.0,
        timeout: float | None = None,
        dest: str | Path | None = None,
        extract: bool = False,
        on_update: Callable[[JobState], None] | None = None,
    ) -> tuple[SimulationExperiment, JobState, list[Path]]:
        """Submit and wait. If the job completed and ``dest`` is given, also save the archive there (or unpack it,
        with ``extract``); the files written, empty otherwise."""
        sim = self.submit(document, simulator=simulator, interval=interval)
        state = self.wait(sim.simulation_database_id, poll=poll, timeout=timeout, on_update=on_update)
        if not (dest and state.ok):
            return sim, state, []
        sid = sim.simulation_database_id
        return sim, state, self.extract(sid, dest) if extract else [self.download(sid, dest)]


class AsyncComposeSession:
    """The asynchronous twin of :class:`ComposeSession`, with the same methods as coroutines."""

    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        *,
        tokens: AsyncTokenSource | None = None,
        token: str | None = None,
        timeout: float = 300.0,
        client: Client | AuthenticatedClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        ca_bundle: Path | None = None,
        allowed_paths: frozenset[str] | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._transport = transport
        self._verify = tls_verification(ca_bundle)
        self._guard = _DestinationGuard(base_url, allowed_paths=allowed_paths)
        self.tokens: AsyncTokenSource | None = (
            tokens if tokens is not None else (StaticToken(token).as_async() if token else None)
        )
        self._provided_client = client
        self._answered: list[httpx.Response] = []
        self._active_token: str | None = token
        self.client = client or _make_client(
            base_url,
            token,
            _read_timeout(timeout),
            transport,
            verify_ssl=self._verify,
            guard=self._guard,
            is_async=True,
            on_response=self._answered.append,
        )

    @classmethod
    def in_process(
        cls,
        app: Any,
        base_url: str = "http://testserver",
        *,
        token: str | None = None,
        tokens: AsyncTokenSource | None = None,
    ) -> AsyncComposeSession:
        """A session on an ASGI app (the FastAPI app) with no network: for tests."""
        if token is not None or tokens is not None:
            return cls(base_url=base_url, token=token, tokens=tokens, transport=httpx.ASGITransport(app=app))
        client = Client(base_url=base_url, raise_on_unexpected_status=False)
        client.set_async_httpx_client(httpx.AsyncClient(base_url=base_url, transport=httpx.ASGITransport(app=app)))
        return cls(base_url=base_url, client=client)

    async def __aenter__(self) -> AsyncComposeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self.client._async_client is not None:
            await self.client._async_client.aclose()
            self.client._async_client = None

    async def _prepare_client(self, token: str | None, timeout: float) -> Client | AuthenticatedClient:
        t = httpx.Timeout(timeout, connect=5.0, write=60.0, pool=5.0)
        if token != self._active_token:
            await self.aclose()
            self.client = _make_client(
                self.base_url,
                token,
                timeout,
                self._transport,
                verify_ssl=self._verify,
                guard=self._guard,
                is_async=True,
                on_response=self._answered.append,
            )
            self._active_token = token
        else:
            self.client._timeout = t
            if self.client._async_client is not None:
                self.client._async_client.timeout = t
        return self.client

    async def _send(
        self,
        op: Operation,
        call: Callable[[Any], Awaitable[Response[Any]]],
        *,
        download: bool = False,
    ) -> tuple[Response[Any], Credential | None]:
        if self._provided_client is not None and self.tokens is None:
            return await call(self.client), None
        credential = await self.tokens.current() if self.tokens is not None else None
        response = await self._attempt(op, credential, call, download=download)
        if int(response.status_code) == 401 and self.tokens is not None and credential is not None:
            credential, response = await self._after_unauthorized(op, credential, call, download=download)
        return response, credential

    async def _after_unauthorized(
        self,
        op: Operation,
        rejected: Credential,
        call: Callable[[Any], Awaitable[Response[Any]]],
        *,
        download: bool = False,
    ) -> tuple[Credential, Response[Any]]:
        if getattr(self.tokens, "environment", False):
            suffix = "" if op.replayable else "; the submission was not sent"
            raise AuthError(rejected_message(renewable=False, env_var=TOKEN_ENV_VAR) + suffix)
        if not op.replayable:
            renewed: Credential | None = None
            if self.tokens is not None:
                with suppress(CliError):
                    renewed = await self.tokens.renew(rejected)
            hint = "the session was renewed, so" if renewed is not None else "sign in again, then"
            raise AuthError(
                f"the API rejected this session's credentials, so the simulation was not submitted; {hint} run the"
                " command again"
            )
        renewed = await self.tokens.renew(rejected) if self.tokens is not None else None
        if renewed is None:
            raise AuthError(rejected_message(renewable=False))
        response = await self._attempt(op, renewed, call, download=download)
        if int(response.status_code) == 401:
            raise AuthError(rejected_message(renewable=True))
        return renewed, response

    async def _attempt(
        self,
        op: Operation,
        credential: Credential | None,
        call: Callable[[Any], Awaitable[Response[Any]]],
        *,
        download: bool = False,
    ) -> Response[Any]:
        self._answered.clear()
        token = credential.access_token if credential is not None else None
        client = await self._prepare_client(token, _read_timeout(self.timeout, download=download))
        try:
            # A download has no overall deadline: a large one can rightly take longer, and the read timeout already
            # ends one that stalls.
            async with asyncio.timeout(None if download else COMMAND_DEADLINE_SECONDS):
                return await call(client)
        except _READ_FAILURES:
            if not self._answered:
                raise  # nothing came back: a bug, not an answer
            return _unreadable(self._answered[-1])
        except UnsafeRequestError:
            raise ProtocolError(_refused(op, credential, self.base_url)) from None
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise NetworkError(
                f"cannot reach {self.base_url}: could not connect to the API at {self.base_url}; check the connection"
                " and api_base_url; the request is known not sent"
            ) from None
        except (TimeoutError, httpx.TimeoutException):
            if not op.replayable:
                raise UncertainOutcomeError(
                    unanswered(op, "did not answer in time"), exit_code=ExitCode.NETWORK
                ) from None
            raise NetworkError(unanswered(op, "did not answer in time")) from None
        except httpx.HTTPError:
            if not op.replayable:
                raise UncertainOutcomeError(
                    unanswered(op, "connection failed before an answer arrived"), exit_code=ExitCode.NETWORK
                ) from None
            raise NetworkError(unanswered(op, "connection failed before an answer arrived")) from None

    async def whoami(self) -> CurrentPrincipalResponse:
        """The identity the service sees for this session's bearer token (GET /auth/me)."""
        r, credential = await self._send(
            CURRENT_PRINCIPAL,
            lambda c: get_current_principal.asyncio_detailed(client=cast(AuthenticatedClient, c)),
        )
        principal: CurrentPrincipalResponse = _parsed(r, op=CURRENT_PRINCIPAL)
        if (
            credential is not None
            and credential.issuer is not None
            and credential.subject is not None
            and (principal.issuer, principal.subject) != (credential.issuer, credential.subject)
        ):
            raise ProtocolError(
                "the API identifies this session as a different user than the one that signed in; check that"
                " api_base_url, auth0_domain and auth0_audience describe the same deployment"
            )
        if self.tokens is not None and credential is not None:
            await self.tokens.confirmed(credential, datetime.datetime.now(datetime.UTC))
        return principal

    async def health(self) -> dict[str, str]:
        op = Operation("GET", "/health", replayable=True)
        r, _ = await self._send(op, lambda c: check_health_health_get.asyncio_detailed(client=c))
        return dict(_parsed(r, op=op).to_dict())

    async def version(self) -> str:
        op = Operation("GET", "/version", replayable=True)
        r, _ = await self._send(op, lambda c: get_version_version_get.asyncio_detailed(client=c))
        return str(_parsed(r, op=op))

    async def simulators(self) -> RegisteredSimulators:
        op = Operation("GET", "/core/simulator/list", replayable=True)
        r, _ = await self._send(op, lambda c: get_simulator_list.asyncio_detailed(client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def processes(self) -> list[BiGraphProcess]:
        op = Operation("GET", "/core/processes/list", replayable=True)
        r, _ = await self._send(op, lambda c: get_processes_list.asyncio_detailed(client=c))
        return list(_parsed(r, op=op))

    async def steps(self) -> list[BiGraphStep]:
        op = Operation("GET", "/core/steps/list", replayable=True)
        r, _ = await self._send(op, lambda c: get_steps_list.asyncio_detailed(client=c))
        return list(_parsed(r, op=op))

    async def environments(self) -> list[EnvironmentSummary]:
        """The environments documents run in, with what their interface manifests hold."""
        op = Operation("GET", "/registry/environments", replayable=True)
        r, _ = await self._send(op, lambda c: list_environments.asyncio_detailed(client=c))
        return list(_parsed(r, op=op))

    async def catalog(self) -> list[CatalogEntry]:
        """Every registry entry with its curation level and the environments that provide its classes."""
        op = Operation("GET", "/registry/entries", replayable=True)
        r, _ = await self._send(op, lambda c: list_registry_entries.asyncio_detailed(client=c))
        return list(_parsed(r, op=op))

    async def solvers(self) -> list[Solver]:
        """The solvers SED-ML runs can use: class, environment, KiSAO algorithms, what each returns."""
        op = Operation("GET", "/registry/solvers", replayable=True)
        r, _ = await self._send(op, lambda c: list_solvers.asyncio_detailed(client=c))
        return list(_parsed(r, op=op))

    async def environment_manifest(self, name: str) -> InterfaceManifest:
        """An environment's interface manifest (pbg-interfaces/1)."""
        op = Operation("GET", f"/registry/environments/{name}/manifest", replayable=True)
        r, _ = await self._send(op, lambda c: get_environment_manifest.asyncio_detailed(name, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def environment_headers(self, name: str) -> EnvironmentHeaders:
        """An environment's interfaces as .pblang header files, and each class's declaration."""
        op = Operation("GET", f"/registry/environments/{name}/headers", replayable=True)
        r, _ = await self._send(op, lambda c: get_environment_headers.asyncio_detailed(name, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def environment_images(self, name: str) -> ImageStatus:
        """Whether an environment's current image is built, with its image records and newest build run."""
        op = Operation("GET", f"/registry/environments/{name}/images", replayable=True)
        r, _ = await self._send(op, lambda c: get_environment_images.asyncio_detailed(name, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def build_environment(self, name: str) -> ImageStatus:
        """Make an environment's current image available: pulled or built unless it is, joining a build under way."""
        op = Operation("POST", f"/registry/environments/{name}/build", replayable=False)
        r, _ = await self._send(op, lambda c: build_environment.asyncio_detailed(name, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def environment_versions(self, name: str) -> EnvironmentVersions:
        """An environment's versions, newest first, and its default (docs/plan-environment-versions.md)."""
        op = Operation("GET", f"/registry/environments/{name}/versions", replayable=True)
        r, _ = await self._send(op, lambda c: list_environment_versions.asyncio_detailed(name, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def environment_version(self, name: str, number: int) -> EnvironmentVersionDetail:
        """One version: what it was made from, its lock, and what it installed and provides."""
        op = Operation("GET", f"/registry/environments/{name}/versions/{number}", replayable=True)
        r, _ = await self._send(op, lambda c: get_environment_version.asyncio_detailed(name, number, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def export_environment_version(
        self,
        name: str,
        number: int,
        *,
        format: str | None = None,  # noqa: A002
    ) -> EnvironmentExport:
        """The files that recreate a version locally: pixi.toml and pixi.lock, or a uv requirements lock."""
        op = Operation("GET", f"/registry/environments/{name}/versions/{number}/export", replayable=True)
        fmt = format if format is not None else UNSET
        r, _ = await self._send(
            op, lambda c: export_environment_version.asyncio_detailed(name, number, client=c, format_=fmt)
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def environment_compliance(self, name: str, number: int) -> ComplianceReport:
        """Where each entry of a version stands there (its cases' runs), and the components a generic check refuses."""
        op = Operation("GET", f"/registry/environments/{name}/versions/{number}/compliance", replayable=True)
        r, _ = await self._send(
            op, lambda c: get_environment_version_compliance.asyncio_detailed(name, number, client=c)
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def run_environment_compliance(self, name: str, number: int) -> ComplianceReport:
        """Run a version's compliance cases again (new runs: sent once, never retried). Needs the environment
        administrator role."""
        op = Operation("POST", f"/registry/environments/{name}/versions/{number}/compliance", replayable=False)
        r, _ = await self._send(
            op, lambda c: run_environment_version_compliance.asyncio_detailed(name, number, client=c)
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def create_environment_version(
        self,
        name: str,
        *,
        resolved_at: datetime.datetime | None = None,
        image: str | None = None,
        note: str | None = None,
    ) -> EnvironmentVersion:
        """A new version (or the existing one with the same definition): a shared environment resolved at
        ``resolved_at`` (default now), or a prebuilt one's ``image`` by digest. Its image is built in the background;
        it does not become the default. Needs the environment administrator role."""
        op = Operation("POST", f"/registry/environments/{name}/versions", replayable=False)
        body = NewEnvironmentVersion(
            resolved_at=resolved_at if resolved_at is not None else UNSET,
            image=image if image is not None else UNSET,
            note=note if note is not None else UNSET,
        )
        r, _ = await self._send(op, lambda c: create_environment_version.asyncio_detailed(name, client=c, body=body))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def set_environment_default(self, name: str, number: int) -> EnvironmentVersion:
        """Make a ready version the one runs get when they name none. Needs the environment administrator role."""
        op = Operation("PUT", f"/registry/environments/{name}/default", replayable=True)
        body = DefaultVersion(number=number)
        r, _ = await self._send(op, lambda c: set_environment_default.asyncio_detailed(name, client=c, body=body))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def retire_environment_version(self, name: str, number: int) -> EnvironmentVersion:
        """Retire a version: it refuses new runs; its images are kept. Needs the environment administrator role."""
        op = Operation("POST", f"/registry/environments/{name}/versions/{number}/retire", replayable=True)
        r, _ = await self._send(op, lambda c: retire_environment_version.asyncio_detailed(name, number, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def inspect_environment_version(self, name: str, number: int) -> EnvironmentVersion:
        """Read a prebuilt version's image back again (what it installed and provides), in the background. Needs the
        environment administrator role."""
        op = Operation("POST", f"/registry/environments/{name}/versions/{number}/inspect", replayable=True)
        r, _ = await self._send(op, lambda c: inspect_environment_version.asyncio_detailed(name, number, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def simulator_images(self, simulator_id: int) -> ImageStatus:
        """Whether a simulator's image is built, with its image records and newest build run."""
        op = Operation("GET", f"/registry/simulators/{simulator_id}/images", replayable=True)
        r, _ = await self._send(op, lambda c: get_simulator_images.asyncio_detailed(simulator_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def build_simulator(self, simulator_id: int) -> ImageStatus:
        """Make a simulator's image available: pulled or built unless it is, joining a build under way."""
        op = Operation("POST", f"/registry/simulators/{simulator_id}/build", replayable=False)
        r, _ = await self._send(op, lambda c: build_simulator.asyncio_detailed(simulator_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def submit(
        self,
        document: FileSource,
        *,
        simulator: str | None = None,
        interval: float = 1.0,
        batch: bool = False,
        tags: Sequence[str] = (),
        description: str | None = None,
        environment_version: int | None = None,
        environment: str | None = None,
    ) -> SimulationExperiment:
        op = Operation("POST", "/simulation/run", replayable=False)
        r, _ = await self._send(
            op,
            lambda c: run_simulation.asyncio_detailed(
                client=c,
                body=BodyRunSimulation(uploaded_file=_file(document)),
                interval_time=interval,
                batch_submission=batch,
                simulator=simulator if simulator is not None else UNSET,
                tags=list(tags) if tags else UNSET,
                description=description if description is not None else UNSET,
                environment_version=environment_version if environment_version is not None else UNSET,
                environment=environment if environment is not None else UNSET,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def submit_copasi(
        self, sbml: FileSource, *, start: float, duration: float, points: int
    ) -> SimulationExperiment:
        op = Operation("POST", "/curated/copasi", replayable=False)
        r, _ = await self._send(
            op,
            lambda c: run_copasi.asyncio_detailed(
                client=c,
                body=BodyRunCopasi(sbml=_file(sbml)),
                start_time=start,
                duration=duration,
                num_data_points=points,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def submit_tellurium(
        self, sbml: FileSource, *, start: float, end: float, points: int
    ) -> SimulationExperiment:
        op = Operation("POST", "/curated/tellurium", replayable=False)
        r, _ = await self._send(
            op,
            lambda c: run_tellurium.asyncio_detailed(
                client=c,
                body=BodyRunTellurium(sbml=_file(sbml)),
                start_time=start,
                end_time=end,
                num_data_points=points,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def status(self, simulation_id: int) -> JobState:
        op = Operation("GET", "/results/simulation/status", replayable=True)
        r, _ = await self._send(
            op, lambda c: get_simulation_status.asyncio_detailed(client=c, simulation_id=simulation_id)
        )
        return _state(r, op=op)

    async def statuses(self, simulation_ids: Sequence[int]) -> list[HpcRun]:
        op = Operation("GET", "/results/simulations/status/batch", replayable=True)
        r, _ = await self._send(
            op, lambda c: get_simulations_status_batch.asyncio_detailed(client=c, body=list(simulation_ids))
        )
        return list(_parsed(r, op=op))

    async def build_log(self, simulator_id: int) -> str:
        """The SLURM log of the simulator's newest container build (its last 200 KB)."""
        op = Operation("GET", "/results/simulator/build/log", replayable=True)
        r, _ = await self._send(
            op, lambda c: get_simulator_build_log.asyncio_detailed(client=c, simulator_id=simulator_id)
        )
        _raise_for(r, op)
        return r.content.decode(errors="replace")

    async def build_status(self, simulator_id: int) -> JobState:
        op = Operation("GET", "/results/simulator/build/status", replayable=True)
        r, _ = await self._send(
            op, lambda c: get_simulator_build_status.asyncio_detailed(client=c, simulator_id=simulator_id)
        )
        return _state(r, op=op)

    async def wait(
        self,
        simulation_id: int,
        *,
        poll: float = 5.0,
        timeout: float | None = None,
        on_update: Callable[[JobState], None] | None = None,
    ) -> JobState:
        return await _wait_async(lambda: self.status(simulation_id), poll, timeout, on_update)

    async def wait_build(
        self,
        simulator_id: int,
        *,
        poll: float = 5.0,
        timeout: float | None = None,
        on_update: Callable[[JobState], None] | None = None,
    ) -> JobState:
        return await _wait_async(lambda: self.build_status(simulator_id), poll, timeout, on_update)

    async def simulations(
        self,
        *,
        status: str | None = None,
        simulator: str | None = None,
        since: datetime.datetime | None = None,
        labels: dict[str, str] | None = None,
        tags: Sequence[str] = (),
        limit: int = 50,
        offset: int = 0,
    ) -> SimulationPage:
        op = Operation("GET", "/simulations", replayable=True)
        r, _ = await self._send(
            op,
            lambda c: list_simulations.asyncio_detailed(
                client=c, **_simulation_filters(status, simulator, since, labels, tags, limit, offset)
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    # -- SED-ML -----------------------------------------------------------------------------------------------------

    async def sedml_preview(self, archive: FileSource, *, solvers: Sequence[str] = ()) -> SedmlPreview:
        """Translate a SED-ML archive without running it: its tasks, and what each solver would run or why not."""
        op = Operation("POST", "/sedml/preview", replayable=True)
        r, _ = await self._send(
            op,
            lambda c: preview_sedml.asyncio_detailed(
                client=c,
                body=BodyPreviewSedml(archive=_file(archive)),
                solvers=list(solvers) if solvers else UNSET,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def sedml_run(
        self,
        archive: FileSource,
        *,
        solvers: Sequence[str] = (),
        tasks: Sequence[str] = (),
        tags: Sequence[str] = (),
        description: str | None = None,
        environment_versions: Sequence[str] = (),
    ) -> SedmlRunResult:
        """Run each task of a SED-ML archive once per solver; one comparison per task. ``environment_versions``:
        ``environment@number`` or ``environment@default``; an environment not named runs at its default."""
        op = Operation("POST", "/sedml/run", replayable=False)
        r, _ = await self._send(
            op,
            lambda c: run_sedml.asyncio_detailed(
                client=c,
                body=BodyRunSedml(archive=_file(archive)),
                solvers=list(solvers) if solvers else UNSET,
                task=list(tasks) if tasks else UNSET,
                tags=list(tags) if tags else UNSET,
                description=description if description is not None else UNSET,
                environment_version=list(environment_versions) if environment_versions else UNSET,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    # -- sources (BioModels, biosimulations.org) --------------------------------------------------------------------

    async def biomodels_search(self, query: str, *, limit: int = 20, curated: bool = True) -> list[BiomodelHit]:
        op = Operation("GET", "/sources/biomodels/search", replayable=True)
        r, _ = await self._send(
            op, lambda c: search_biomodels.asyncio_detailed(client=c, q=query, limit=limit, curated=curated)
        )
        return list(_parsed(r, op=op))

    async def biomodel(self, model_id: str) -> BiomodelInfo:
        op = Operation("GET", f"/sources/biomodels/{model_id}", replayable=True)
        r, _ = await self._send(op, lambda c: get_biomodel.asyncio_detailed(model_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def biomodel_omex(self, model_id: str) -> bytes:
        op = Operation("GET", f"/sources/biomodels/{model_id}/omex", replayable=True)
        r, _ = await self._send(op, lambda c: get_biomodel_omex.asyncio_detailed(model_id, client=c), download=True)
        _raise_for(r, op)
        return r.content

    async def run_biomodel(
        self,
        model_id: str,
        *,
        solvers: Sequence[str] = (),
        tags: Sequence[str] = (),
        environment_versions: Sequence[str] = (),
    ) -> SedmlRunResult:
        op = Operation("POST", f"/sources/biomodels/{model_id}/run", replayable=False)
        r, _ = await self._send(
            op,
            lambda c: run_biomodel.asyncio_detailed(
                model_id,
                client=c,
                solvers=list(solvers) if solvers else UNSET,
                tags=list(tags) if tags else UNSET,
                environment_version=list(environment_versions) if environment_versions else UNSET,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def biosimulations_search(self, query: str = "", *, limit: int = 20) -> list[ProjectInfo]:
        op = Operation("GET", "/sources/biosimulations/projects", replayable=True)
        r, _ = await self._send(
            op, lambda c: search_biosimulations_projects.asyncio_detailed(client=c, q=query, limit=limit)
        )
        return list(_parsed(r, op=op))

    async def biosimulations_project(self, project_id: str) -> ProjectInfo:
        op = Operation("GET", f"/sources/biosimulations/{project_id}", replayable=True)
        r, _ = await self._send(op, lambda c: get_biosimulations_project.asyncio_detailed(project_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def biosimulations_omex(self, project_id: str) -> bytes:
        op = Operation("GET", f"/sources/biosimulations/{project_id}/omex", replayable=True)
        r, _ = await self._send(
            op, lambda c: get_biosimulations_omex.asyncio_detailed(project_id, client=c), download=True
        )
        _raise_for(r, op)
        return r.content

    async def biosimulations_reference(self, project_id: str) -> dict[str, dict[str, list[float]]]:
        """The project's original results: `{"<sedml>/<report>": {label: values}}`."""
        op = Operation("GET", f"/sources/biosimulations/{project_id}/reference", replayable=True)
        r, _ = await self._send(op, lambda c: get_biosimulations_reference.asyncio_detailed(project_id, client=c))
        _raise_for(r, op)
        data: dict[str, dict[str, list[float]]] = r.parsed.to_dict()  # type: ignore[union-attr]
        return data

    async def run_biosimulations_project(
        self,
        project_id: str,
        *,
        solvers: Sequence[str] = (),
        tags: Sequence[str] = (),
        environment_versions: Sequence[str] = (),
    ) -> SedmlRunResult:
        op = Operation("POST", f"/sources/biosimulations/{project_id}/run", replayable=False)
        r, _ = await self._send(
            op,
            lambda c: run_biosimulations_project.asyncio_detailed(
                project_id,
                client=c,
                solvers=list(solvers) if solvers else UNSET,
                tags=list(tags) if tags else UNSET,
                environment_version=list(environment_versions) if environment_versions else UNSET,
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    # -- suites -----------------------------------------------------------------------------------------------------

    async def suites(self) -> list[Suite]:
        op = Operation("GET", "/suites", replayable=True)
        r, _ = await self._send(op, lambda c: list_suites.asyncio_detailed(client=c))
        return list(_parsed(r, op=op))

    async def suite_runs(self, name: str) -> list[SuiteRunInfo]:
        op = Operation("GET", f"/suites/{name}/runs", replayable=True)
        r, _ = await self._send(op, lambda c: list_suite_runs.asyncio_detailed(name, client=c))
        return list(_parsed(r, op=op))

    async def suite_run(self, name: str, number: int) -> SuiteRunView:
        """One suite run: per source, agreement, references, and drift from the baseline run."""
        op = Operation("GET", f"/suites/{name}/runs/{number}", replayable=True)
        r, _ = await self._send(op, lambda c: get_suite_run.asyncio_detailed(name, number, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def run_suite(self, name: str, *, environment_versions: Sequence[str]) -> SuiteRunInfo:
        """Run every source of the suite (submitted in the background) in the environment versions named:
        ``environment@number``, ``environment@default``, or ``default`` (each at its default); the new run's number."""
        op = Operation("POST", f"/suites/{name}/run", replayable=False)
        r, _ = await self._send(
            op, lambda c: run_suite.asyncio_detailed(name, client=c, environment_version=list(environment_versions))
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def comparisons(self, *, source: str | None = None, limit: int = 25, offset: int = 0) -> ComparisonPage:
        op = Operation("GET", "/comparisons", replayable=True)
        r, _ = await self._send(
            op,
            lambda c: list_comparisons.asyncio_detailed(
                client=c, source=source if source is not None else UNSET, limit=limit, offset=offset
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def comparison_series(self, comparison_id: int, report: str) -> ComparisonSeries:
        """One report's columns from each run and each reference."""
        op = Operation("GET", f"/comparisons/{comparison_id}/series", replayable=True)
        r, _ = await self._send(
            op, lambda c: get_comparison_series.asyncio_detailed(comparison_id, client=c, report=report)
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def comparison(self, comparison_id: int) -> Comparison:
        """One comparison: its runs, and per report and data set each solver pair's score once all have finished."""
        op = Operation("GET", f"/comparisons/{comparison_id}", replayable=True)
        r, _ = await self._send(op, lambda c: get_comparison.asyncio_detailed(comparison_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def verify_comparison(self, comparison_id: int, simulators: list[str] | None = None) -> Verification:
        """Queue a check of the comparison against BioSimulators' simulators (biosim's /verify); one already queued
        or running for the same simulators is returned instead."""
        op = Operation("POST", f"/comparisons/{comparison_id}/verify", replayable=False)
        body = VerifyRequest(simulators=simulators) if simulators else None  # no body: the service's default
        r, _ = await self._send(op, lambda c: verify_comparison.asyncio_detailed(comparison_id, client=c, body=body))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def comparison_verifications(self, comparison_id: int) -> list[Verification]:
        """The comparison's verifications, oldest first."""
        op = Operation("GET", f"/comparisons/{comparison_id}/verifications", replayable=True)
        r, _ = await self._send(op, lambda c: list_comparison_verifications.asyncio_detailed(comparison_id, client=c))
        return list(_parsed(r, op=op))

    async def verify_suite_run(self, name: str, number: int, *, which: str = "failing") -> SuiteVerifyResult:
        """Queue verifications for a suite run's finished comparisons: ``failing`` ones, or ``all``."""
        op = Operation("POST", f"/suites/{name}/runs/{number}/verify", replayable=False)
        r, _ = await self._send(
            op, lambda c: verify_suite_run.asyncio_detailed(name, number, client=c, which=VerifySuiteRunWhich(which))
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def suite_problems(self, name: str, *, cleared: bool | None = None) -> list[KnownProblem]:
        """A suite's known problems, oldest first: every one, or only the cleared (True) or open (False) ones."""
        op = Operation("GET", f"/suites/{name}/problems", replayable=True)
        flag = cleared if cleared is not None else UNSET
        r, _ = await self._send(op, lambda c: list_suite_problems.asyncio_detailed(name, client=c, cleared=flag))
        return list(_parsed(r, op=op))

    async def mark_suite_problem(
        self,
        name: str,
        source: str,
        *,
        category: str,
        reason: str,
        solver: str | None = None,
        seen_run: int | None = None,
    ) -> KnownProblem:
        """Record a known problem of a solver (or of every solver) on a suite's source (sent once, never retried).
        Needs the suite curator role."""
        op = Operation("POST", f"/suites/{name}/problems", replayable=False)
        mark = KnownProblemMark(
            source=source,
            category=category,
            reason=reason,
            solver=solver if solver is not None else UNSET,
            seen_run=seen_run if seen_run is not None else UNSET,
        )
        r, _ = await self._send(op, lambda c: mark_suite_problem.asyncio_detailed(name, client=c, body=mark))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def edit_suite_problem(
        self, name: str, problem_id: int, *, category: str | None = None, reason: str | None = None
    ) -> KnownProblem:
        """Change a known problem's category or reason. Needs the suite curator role."""
        op = Operation("PATCH", f"/suites/{name}/problems/{problem_id}", replayable=True)
        edit = KnownProblemEdit(
            category=category if category is not None else UNSET, reason=reason if reason is not None else UNSET
        )
        r, _ = await self._send(
            op, lambda c: edit_suite_problem.asyncio_detailed(name, problem_id, client=c, body=edit)
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def clear_suite_problem(self, name: str, problem_id: int, run: int) -> KnownProblem:
        """Clear a known problem at the suite run that shows it fixed. Needs the suite curator role."""
        op = Operation("POST", f"/suites/{name}/problems/{problem_id}/clear", replayable=True)
        body = KnownProblemClear(run=run)
        r, _ = await self._send(
            op, lambda c: clear_suite_problem.asyncio_detailed(name, problem_id, client=c, body=body)
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def simulation(self, simulation_id: int) -> SimulationDetail:
        op = Operation("GET", f"/simulations/{simulation_id}", replayable=True)
        r, _ = await self._send(op, lambda c: get_simulation.asyncio_detailed(simulation_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def cancel_simulation(self, simulation_id: int) -> SimulationCancellation:
        op = Operation("DELETE", f"/simulations/{simulation_id}", replayable=False)
        r, _ = await self._send(op, lambda c: cancel_simulation.asyncio_detailed(simulation_id, client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def events(
        self,
        simulation_id: int,
        *,
        after: int | None = None,
        limit: int = 500,
        level: str | None = None,
        event: str | None = None,
        span_id: str | None = None,
    ) -> RunEventPage:
        op = Operation("GET", "/results/simulation/events", replayable=True)
        r, _ = await self._send(
            op,
            lambda c: get_simulation_events.asyncio_detailed(
                client=c, simulation_id=simulation_id, **_event_filters(after, limit, level, event, span_id)
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def trace(self, simulation_id: int) -> RunTraceTree:
        op = Operation("GET", "/results/simulation/trace", replayable=True)
        r, _ = await self._send(
            op, lambda c: get_simulation_trace.asyncio_detailed(client=c, simulation_id=simulation_id)
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def trace_chrome(self, simulation_id: int) -> dict[str, Any]:
        op = Operation("GET", "/results/simulation/trace/chrome", replayable=True)
        r, _ = await self._send(
            op, lambda c: get_simulation_trace_chrome.asyncio_detailed(client=c, simulation_id=simulation_id)
        )
        return dict(_parsed(r, op=op).to_dict())

    async def datasets(
        self,
        *,
        simulation_id: int | None = None,
        kind: str | None = None,
        q: str | None = None,
        available: bool | None = True,
        limit: int = 100,
        offset: int = 0,
    ) -> DatasetPage:
        op = Operation("GET", "/datasets", replayable=True)
        r, _ = await self._send(
            op,
            lambda c: list_datasets.asyncio_detailed(
                client=c, **_dataset_filters(simulation_id, kind, q, available, limit, offset)
            ),
        )
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def dataset(self, dataset_id: str | uuid.UUID) -> Dataset:
        op = Operation("GET", f"/datasets/{dataset_id}", replayable=True)
        r, _ = await self._send(op, lambda c: get_dataset.asyncio_detailed(uuid.UUID(str(dataset_id)), client=c))
        return _parsed(r, op=op)  # type: ignore[no-any-return]

    async def dataset_content(self, dataset_id: str | uuid.UUID) -> bytes:
        op = Operation("GET", f"/datasets/{dataset_id}/content", replayable=True)
        r, _ = await self._send(
            op, lambda c: get_dataset_content.asyncio_detailed(uuid.UUID(str(dataset_id)), client=c), download=True
        )
        _raise_for(r, op)
        return r.content

    async def results(self, simulation_id: int) -> bytes:
        op = Operation("GET", "/results/simulation/results/file", replayable=True)
        r, _ = await self._send(
            op,
            lambda c: get_simulation_results_file.asyncio_detailed(client=c, simulation_id=simulation_id),
            download=True,
        )
        _raise_for(r, op)
        return r.content

    async def download(self, simulation_id: int, dest: str | Path) -> Path:
        return _save(await self.results(simulation_id), simulation_id, dest)

    async def extract(self, simulation_id: int, dest: str | Path) -> list[Path]:
        return _extract(await self.results(simulation_id), dest)

    async def run_and_wait(
        self,
        document: FileSource,
        *,
        simulator: str | None = None,
        interval: float = 1.0,
        poll: float = 5.0,
        timeout: float | None = None,
        dest: str | Path | None = None,
        extract: bool = False,
        on_update: Callable[[JobState], None] | None = None,
    ) -> tuple[SimulationExperiment, JobState, list[Path]]:
        sim = await self.submit(document, simulator=simulator, interval=interval)
        state = await self.wait(sim.simulation_database_id, poll=poll, timeout=timeout, on_update=on_update)
        if not (dest and state.ok):
            return sim, state, []
        sid = sim.simulation_database_id
        return sim, state, await self.extract(sid, dest) if extract else [await self.download(sid, dest)]


def _simulation_filters(
    status: str | None,
    simulator: str | None,
    since: datetime.datetime | None,
    labels: dict[str, str] | None,
    tags: Sequence[str],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    return {
        "status": ListSimulationsStatusType0(status) if status is not None else UNSET,
        "simulator": simulator if simulator is not None else UNSET,
        "since": since if since is not None else UNSET,
        "label": [f"{k}:{v}" for k, v in labels.items()] if labels else UNSET,
        "tag": list(tags) if tags else UNSET,
        "limit": limit,
        "offset": offset,
    }


def _dataset_filters(
    simulation_id: int | None, kind: str | None, q: str | None, available: bool | None, limit: int, offset: int
) -> dict[str, Any]:
    return {
        "simulation_id": simulation_id if simulation_id is not None else UNSET,
        "kind": kind if kind is not None else UNSET,
        "q": q if q is not None else UNSET,
        "available": available,
        "limit": limit,
        "offset": offset,
    }


def _event_filters(
    after: int | None, limit: int, level: str | None, event: str | None, span_id: str | None
) -> dict[str, Any]:
    """The events operation's optional query parameters, unset when not given."""
    return {
        "after": after if after is not None else UNSET,
        "limit": limit,
        "level": level if level is not None else UNSET,
        "event": event if event is not None else UNSET,
        "span_id": span_id if span_id is not None else UNSET,
    }


def _wait_sync(
    get: Callable[[], JobState], poll: float, timeout: float | None, on_update: Callable[[JobState], None] | None
) -> JobState:
    deadline = None if timeout is None else time.monotonic() + timeout
    last: JobState | None = None
    while True:
        state = get()
        if on_update and (last is None or state.status != last.status):
            on_update(state)
        last = state
        if state.terminal:
            return state
        if deadline is not None and time.monotonic() >= deadline:
            raise ApiTimeout(f"still {state.status} after {timeout} s", last)
        time.sleep(poll)


async def _wait_async(
    get: Callable[[], Awaitable[JobState]],
    poll: float,
    timeout: float | None,
    on_update: Callable[[JobState], None] | None,
) -> JobState:
    deadline = None if timeout is None else time.monotonic() + timeout
    last: JobState | None = None
    while True:
        state = await get()
        if on_update and (last is None or state.status != last.status):
            on_update(state)
        last = state
        if state.terminal:
            return state
        if deadline is not None and time.monotonic() >= deadline:
            raise ApiTimeout(f"still {state.status} after {timeout} s", last)
        await asyncio.sleep(poll)


__all__ = [
    "DEFAULT_URL",
    "SUBMITTING",
    "TERMINAL",
    "AsyncComposeSession",
    "ComposeSession",
    "FileSource",
    "JobState",
]
