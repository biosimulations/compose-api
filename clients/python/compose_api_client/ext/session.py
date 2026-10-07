"""Sessions over the generated client: submit, status, wait, results, the catalogue.

``ComposeSession`` is synchronous and ``AsyncComposeSession`` asynchronous; they offer the same methods. Both wrap a
generated ``Client`` (or ``AuthenticatedClient`` when given a token) and turn its detailed responses into return values
or the typed errors of :mod:`compose_api_client.ext.errors`.

    with ComposeSession() as s:                       # https://compose.cam.uchc.edu
        sim = s.submit("experiment.omex", simulator="viva-pde-particle")
        run = s.wait(sim.simulation_database_id)
        s.extract(sim.simulation_database_id, "out/")

In tests, ``AsyncComposeSession.in_process(app)`` talks to the FastAPI app through ``httpx.ASGITransport``.
"""

from __future__ import annotations

import asyncio
import io
import time
import zipfile
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
from attrs import define

from compose_api_client import AuthenticatedClient, Client
from compose_api_client.api.biosim_api import check_health_health_get, get_version_version_get
from compose_api_client.api.compute import get_processes_list, get_simulator_list, get_steps_list
from compose_api_client.api.curated import run_copasi, run_tellurium
from compose_api_client.api.results import (
    get_simulation_results_file,
    get_simulation_status,
    get_simulations_status_batch,
    get_simulator_build_status,
)
from compose_api_client.api.simulation import run_simulation
from compose_api_client.ext.errors import ApiTimeout, raise_for
from compose_api_client.models import (
    BiGraphProcess,
    BiGraphStep,
    BodyRunCopasi,
    BodyRunSimulation,
    BodyRunTellurium,
    HpcRun,
    RegisteredSimulators,
    SimulationExperiment,
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


def _parsed(response: Response[Any]) -> Any:
    raise_for(response)
    return response.parsed


def _state(response: Response[Any]) -> JobState:
    if int(response.status_code) == 404:
        return JobState(SUBMITTING)
    run = _parsed(response)
    return JobState.of(run)


def _save(content: bytes, sim_id: int, dest: str | Path) -> Path:
    path = Path(dest)
    if path.is_dir() or str(dest).endswith(("/", "\\")):
        path.mkdir(parents=True, exist_ok=True)
        path = path / f"simulation_{sim_id}_results.zip"
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


def _make_client(
    base_url: str, token: str | None, timeout: float, transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None
) -> Client | AuthenticatedClient:
    args: dict[str, Any] = {"transport": transport} if transport is not None else {}
    t = httpx.Timeout(timeout)
    if token:
        return AuthenticatedClient(base_url=base_url, token=token, timeout=t, httpx_args=args)
    return Client(base_url=base_url, timeout=t, httpx_args=args)


class ComposeSession:
    """Synchronous access to compose-api. A context manager; ``close()`` releases the connection pool."""

    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        *,
        token: str | None = None,
        timeout: float = 300.0,
        client: Client | AuthenticatedClient | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.client = client or _make_client(base_url, token, timeout, transport)

    def __enter__(self) -> ComposeSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.client.get_httpx_client().close()

    # -- service ----------------------------------------------------------------------------------------------------

    def health(self) -> dict[str, str]:
        return dict(_parsed(check_health_health_get.sync_detailed(client=self.client)).to_dict())

    def version(self) -> str:
        return str(_parsed(get_version_version_get.sync_detailed(client=self.client)))

    def simulators(self) -> RegisteredSimulators:
        return _parsed(get_simulator_list.sync_detailed(client=self.client))  # type: ignore[no-any-return]

    def processes(self) -> list[BiGraphProcess]:
        return list(_parsed(get_processes_list.sync_detailed(client=self.client)))

    def steps(self) -> list[BiGraphStep]:
        return list(_parsed(get_steps_list.sync_detailed(client=self.client)))

    # -- submit -----------------------------------------------------------------------------------------------------

    def submit(
        self, document: FileSource, *, simulator: str | None = None, interval: float = 1.0, batch: bool = False
    ) -> SimulationExperiment:
        """Submit an ``.omex`` (or ``.pbg``). ``simulator`` names a prebuilt simulator image."""
        r = run_simulation.sync_detailed(
            client=self.client,
            body=BodyRunSimulation(uploaded_file=_file(document)),
            interval_time=interval,
            batch_submission=batch,
            simulator=simulator if simulator is not None else UNSET,
        )
        return _parsed(r)  # type: ignore[no-any-return]

    def submit_copasi(self, sbml: FileSource, *, start: float, duration: float, points: int) -> SimulationExperiment:
        r = run_copasi.sync_detailed(
            client=self.client,
            body=BodyRunCopasi(sbml=_file(sbml)),
            start_time=start,
            duration=duration,
            num_data_points=points,
        )
        return _parsed(r)  # type: ignore[no-any-return]

    def submit_tellurium(self, sbml: FileSource, *, start: float, end: float, points: int) -> SimulationExperiment:
        r = run_tellurium.sync_detailed(
            client=self.client,
            body=BodyRunTellurium(sbml=_file(sbml)),
            start_time=start,
            end_time=end,
            num_data_points=points,
        )
        return _parsed(r)  # type: ignore[no-any-return]

    # -- status and waiting ---------------------------------------------------------------------------------------

    def status(self, simulation_id: int) -> JobState:
        return _state(get_simulation_status.sync_detailed(client=self.client, simulation_id=simulation_id))

    def statuses(self, simulation_ids: Sequence[int]) -> list[HpcRun]:
        """Several simulations' job records in one call (only those with a SLURM job yet)."""
        r = get_simulations_status_batch.sync_detailed(client=self.client, body=list(simulation_ids))
        return list(_parsed(r))

    def build_status(self, simulator_id: int) -> JobState:
        return _state(get_simulator_build_status.sync_detailed(client=self.client, simulator_id=simulator_id))

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

    # -- results ----------------------------------------------------------------------------------------------------

    def results(self, simulation_id: int) -> bytes:
        """The results archive (zip). :class:`NotFound` until the simulation has finished."""
        r = get_simulation_results_file.sync_detailed(client=self.client, simulation_id=simulation_id)
        raise_for(r)
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
        token: str | None = None,
        timeout: float = 300.0,
        client: Client | AuthenticatedClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.client = client or _make_client(base_url, token, timeout, transport)

    @classmethod
    def in_process(cls, app: Any, base_url: str = "http://testserver") -> AsyncComposeSession:
        """A session on an ASGI app (the FastAPI app) with no network: for tests."""
        client = Client(base_url=base_url, raise_on_unexpected_status=False)
        client.set_async_httpx_client(httpx.AsyncClient(base_url=base_url, transport=httpx.ASGITransport(app=app)))
        return cls(client=client)

    async def __aenter__(self) -> AsyncComposeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.client.get_async_httpx_client().aclose()

    async def health(self) -> dict[str, str]:
        return dict(_parsed(await check_health_health_get.asyncio_detailed(client=self.client)).to_dict())

    async def version(self) -> str:
        return str(_parsed(await get_version_version_get.asyncio_detailed(client=self.client)))

    async def simulators(self) -> RegisteredSimulators:
        return _parsed(await get_simulator_list.asyncio_detailed(client=self.client))  # type: ignore[no-any-return]

    async def processes(self) -> list[BiGraphProcess]:
        return list(_parsed(await get_processes_list.asyncio_detailed(client=self.client)))

    async def steps(self) -> list[BiGraphStep]:
        return list(_parsed(await get_steps_list.asyncio_detailed(client=self.client)))

    async def submit(
        self, document: FileSource, *, simulator: str | None = None, interval: float = 1.0, batch: bool = False
    ) -> SimulationExperiment:
        r = await run_simulation.asyncio_detailed(
            client=self.client,
            body=BodyRunSimulation(uploaded_file=_file(document)),
            interval_time=interval,
            batch_submission=batch,
            simulator=simulator if simulator is not None else UNSET,
        )
        return _parsed(r)  # type: ignore[no-any-return]

    async def submit_copasi(
        self, sbml: FileSource, *, start: float, duration: float, points: int
    ) -> SimulationExperiment:
        r = await run_copasi.asyncio_detailed(
            client=self.client,
            body=BodyRunCopasi(sbml=_file(sbml)),
            start_time=start,
            duration=duration,
            num_data_points=points,
        )
        return _parsed(r)  # type: ignore[no-any-return]

    async def submit_tellurium(
        self, sbml: FileSource, *, start: float, end: float, points: int
    ) -> SimulationExperiment:
        r = await run_tellurium.asyncio_detailed(
            client=self.client,
            body=BodyRunTellurium(sbml=_file(sbml)),
            start_time=start,
            end_time=end,
            num_data_points=points,
        )
        return _parsed(r)  # type: ignore[no-any-return]

    async def status(self, simulation_id: int) -> JobState:
        return _state(await get_simulation_status.asyncio_detailed(client=self.client, simulation_id=simulation_id))

    async def statuses(self, simulation_ids: Sequence[int]) -> list[HpcRun]:
        r = await get_simulations_status_batch.asyncio_detailed(client=self.client, body=list(simulation_ids))
        return list(_parsed(r))

    async def build_status(self, simulator_id: int) -> JobState:
        return _state(await get_simulator_build_status.asyncio_detailed(client=self.client, simulator_id=simulator_id))

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

    async def results(self, simulation_id: int) -> bytes:
        r = await get_simulation_results_file.asyncio_detailed(client=self.client, simulation_id=simulation_id)
        raise_for(r)
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
