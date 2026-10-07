"""``compose-api``: the command line for compose-api (docs/plan-cli.md, step C).

Every API operation is claimed by exactly one command (``@claims``); ``tests/client/test_cli.py`` fails when the
spec has an operation no command claims, or a command claims one the spec lacks.

Exit codes: 0 success; 1 the job ended other than completed; 2 usage; 3 API error; 4 not found; 5 a wait timed out;
130 interrupted.
"""

from __future__ import annotations

import functools
import importlib.resources
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypeVar

import httpx
import typer

from compose_api_client.cli.render import Output, emit, err, lines
from compose_api_client.ext import (
    DEFAULT_URL,
    ApiTimeout,
    BadRequest,
    ComposeApiError,
    ComposeSession,
    JobState,
    NotFound,
)

EXIT_JOB, EXIT_USAGE, EXIT_API, EXIT_NOT_FOUND, EXIT_TIMEOUT, EXIT_INTERRUPT = 1, 2, 3, 4, 5, 130

CLAIMS: dict[str, str] = {}  # operationId -> command
F = TypeVar("F", bound=Callable[..., Any])


def claims(command: str, *operation_ids: str) -> Callable[[F], F]:
    """Record that ``command`` exercises ``operation_ids``."""

    def mark(fn: F) -> F:
        for op in operation_ids:
            if op in CLAIMS:
                raise RuntimeError(f"{op} is claimed by both {CLAIMS[op]!r} and {command!r}")
            CLAIMS[op] = command
        return fn

    return mark


@dataclass
class Settings:
    url: str = DEFAULT_URL
    timeout: float = 300.0
    output: Output = Output.AUTO
    token: str | None = None
    verbose: bool = False
    quiet: bool = False


def make_session(settings: Settings) -> ComposeSession:
    """The session every command uses. Tests replace this to inject a transport."""
    return ComposeSession(settings.url, token=settings.token, timeout=settings.timeout)


app = typer.Typer(
    name="compose-api",
    help="Drive compose-api: submit simulations, wait for them, fetch results, inspect the catalogue.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
simulators_app = typer.Typer(help="Registered simulator versions.", no_args_is_help=True)
processes_app = typer.Typer(help="Registered process-bigraph processes.", no_args_is_help=True)
steps_app = typer.Typer(help="Registered process-bigraph steps.", no_args_is_help=True)
curated_app = typer.Typer(help="Run an SBML model with a curated simulator.", no_args_is_help=True)
app.add_typer(simulators_app, name="simulators")
app.add_typer(processes_app, name="processes")
app.add_typer(steps_app, name="steps")
app.add_typer(curated_app, name="curated")


@app.callback()
def root(
    ctx: typer.Context,
    url: Annotated[str, typer.Option(envvar="COMPOSE_API_URL", help="Service base URL.")] = DEFAULT_URL,
    timeout: Annotated[float, typer.Option(envvar="COMPOSE_API_TIMEOUT", help="HTTP timeout, seconds.")] = 300.0,
    output: Annotated[
        Output,
        typer.Option("--output", "-o", envvar="COMPOSE_API_OUTPUT", help="auto: table on a terminal, else json."),
    ] = Output.AUTO,
    token: Annotated[
        str | None, typer.Option(envvar="COMPOSE_API_TOKEN", help="Bearer token (when auth is on).")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log HTTP requests; tracebacks on errors.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="No progress lines.")] = False,
) -> None:
    ctx.obj = Settings(url=url, timeout=timeout, output=output, token=token, verbose=verbose, quiet=quiet)
    if verbose:
        import logging

        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logging.getLogger("httpx").setLevel(logging.INFO)


def _settings(ctx: typer.Context) -> Settings:
    obj = ctx.find_root().obj
    return obj if isinstance(obj, Settings) else Settings()


def _report(e: BaseException, settings: Settings) -> int | None:
    """Print ``e`` to stderr and return its exit code; ``None`` for an exception the CLI does not own."""
    if isinstance(e, KeyboardInterrupt):
        err.print("[yellow]interrupted[/]")
        return EXIT_INTERRUPT
    if isinstance(e, NotFound):
        err.print(f"[red]not found[/]: {_detail(e.detail)}")
        return EXIT_NOT_FOUND
    if isinstance(e, BadRequest):
        err.print(f"[red]rejected ({e.status_code})[/]: {_detail(e.detail)}")
        for v in e.violations:
            err.print(f"  - {v if isinstance(v, str) else json.dumps(v, default=str)}")
        return EXIT_API
    if isinstance(e, ComposeApiError):
        err.print(f"[red]compose-api error ({e.status_code})[/]: {_detail(e.detail)}")
        return EXIT_API
    if isinstance(e, ApiTimeout):
        err.print(f"[red]timed out[/]: {e}")
        return EXIT_TIMEOUT
    if isinstance(e, httpx.HTTPError):
        err.print(f"[red]cannot reach {settings.url}[/]: {e}")
        return EXIT_API
    if isinstance(e, (FileNotFoundError, IsADirectoryError)):
        err.print(f"[red]{e}[/]")
        return EXIT_USAGE
    return None


def handled(fn: F) -> F:
    """Map exceptions to a message on stderr and the documented exit code (``--verbose`` re-raises)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx = next((a for a in args if isinstance(a, typer.Context)), kwargs.get("ctx"))
        settings = _settings(ctx) if isinstance(ctx, typer.Context) else Settings()
        try:
            return fn(*args, **kwargs)
        except typer.Exit:
            raise
        except (Exception, KeyboardInterrupt) as e:
            code = _report(e, settings)
            if code is None or settings.verbose:
                raise
            raise typer.Exit(code) from None

    return wrapper  # type: ignore[return-value]


def _detail(detail: Any) -> str:
    if isinstance(detail, dict) and "message" in detail:
        return str(detail["message"])
    return detail if isinstance(detail, str) else json.dumps(detail, default=str)


def _progress(settings: Settings, label: str) -> Callable[[JobState], None]:
    start = time.monotonic()

    def show(state: JobState) -> None:
        if settings.quiet:
            return
        job = f" (slurm {state.slurm_job})" if state.slurm_job else ""
        err.print(f"[dim]{time.monotonic() - start:5.0f}s[/] {label}: [bold]{state.status}[/]{job}")

    return show


def _state_record(sim_id: int, state: JobState) -> dict[str, Any]:
    rec: dict[str, Any] = {"simulation_id": sim_id, "status": state.status}
    if state.record is not None:
        rec |= {k: v for k, v in state.record.to_dict().items() if k not in ("status",)}
    return rec


def _finish_job(
    ctx: typer.Context,
    s: ComposeSession,
    sim_id: int,
    *,
    poll: float,
    wait_timeout: float | None,
    download: Path | None,
    extract: bool,
) -> None:
    settings = _settings(ctx)
    state = s.wait(sim_id, poll=poll, timeout=wait_timeout, on_update=_progress(settings, f"simulation {sim_id}"))
    rec = _state_record(sim_id, state)
    if state.ok and download is not None:
        files = s.extract(sim_id, download) if extract else [s.download(sim_id, f"{download}/")]
        rec["files"] = [str(f) for f in files]
    emit(settings.output, rec)
    if not state.ok:
        raise typer.Exit(EXIT_JOB)


# -- service ------------------------------------------------------------------------------------------------------


@app.command()
@claims("health", "check_health_health_get")
@handled
def health(ctx: typer.Context) -> None:
    """Is the service up, and which version."""
    with make_session(_settings(ctx)) as s:
        emit(_settings(ctx).output, s.health())


@app.command()
@claims("version", "get_version_version_get")
@handled
def version(ctx: typer.Context) -> None:
    """The service's version."""
    with make_session(_settings(ctx)) as s:
        v = s.version()
    if _settings(ctx).output is Output.JSON:
        emit(Output.JSON, v)
    else:
        lines([v])


@simulators_app.command("list")
@claims("simulators list", "get-simulator-list")
@handled
def simulators_list(ctx: typer.Context) -> None:
    """Simulator versions: id, definition hash, base image, creation time."""
    with make_session(_settings(ctx)) as s:
        reg = s.simulators()
    rows = []
    for v in reg.versions:
        rep = v.container_def.representation
        base = next((ln.split(":", 1)[1].strip() for ln in rep.splitlines() if ln.startswith("From:")), "")
        rows.append({
            "id": v.database_id,
            "hash": v.container_def_hash,
            "base_image": base,
            "packages": len(v.packages or []),
            "created_at": str(v.created_at) if v.created_at else None,
        })
    settings = _settings(ctx)
    emit(
        settings.output,
        rows if settings.output is not Output.JSON else reg,
        ["id", "hash", "base_image", "packages", "created_at"],
    )


@processes_app.command("list")
@claims("processes list", "get-processes-list")
@handled
def processes_list(ctx: typer.Context) -> None:
    """Registered processes."""
    with make_session(_settings(ctx)) as s:
        emit(_settings(ctx).output, s.processes(), ["database_id", "name", "module", "compute_type"])


@steps_app.command("list")
@claims("steps list", "get-steps-list")
@handled
def steps_list(ctx: typer.Context) -> None:
    """Registered steps."""
    with make_session(_settings(ctx)) as s:
        emit(_settings(ctx).output, s.steps(), ["database_id", "name", "module", "compute_type"])


# -- running ------------------------------------------------------------------------------------------------------

Poll = Annotated[float, typer.Option(help="Seconds between status checks.")]
WaitTimeout = Annotated[float | None, typer.Option(help="Give up waiting after this many seconds (exit 5).")]
Wait = Annotated[bool, typer.Option("--wait", "-w", help="Wait for the job to finish; exit 1 unless it completed.")]
Download = Annotated[
    Path | None, typer.Option("--download", "-d", help="With --wait: save the results archive into this directory.")
]
Extract = Annotated[bool, typer.Option(help="With --download: unpack the archive instead of saving the zip.")]


@app.command()
@claims("run", "run-simulation")
@handled
def run(
    ctx: typer.Context,
    document: Annotated[Path, typer.Argument(help="The .omex (or .pbg) to run.", exists=True, dir_okay=False)],
    simulator: Annotated[str | None, typer.Option(help="A prebuilt simulator image by name.")] = None,
    interval: Annotated[float, typer.Option(help="Simulation interval passed to the runner.")] = 1.0,
    batch: Annotated[bool, typer.Option(help="Submit as a batch job (smaller partition, 1 CPU).")] = False,
    wait: Wait = False,
    download: Download = None,
    extract: Extract = False,
    poll: Poll = 5.0,
    wait_timeout: WaitTimeout = None,
) -> None:
    """Submit a simulation. Prints its ids; with --wait, its final state (and the files, with --download)."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        sim = s.submit(document, simulator=simulator, interval=interval, batch=batch)
        if not wait:
            emit(settings.output, sim)
            return
        if not settings.quiet:
            err.print(f"submitted simulation {sim.simulation_database_id}")
        _finish_job(
            ctx, s, sim.simulation_database_id, poll=poll, wait_timeout=wait_timeout, download=download, extract=extract
        )


@curated_app.command("copasi")
@claims("curated copasi", "run-copasi")
@handled
def curated_copasi(
    ctx: typer.Context,
    sbml: Annotated[Path, typer.Argument(help="The SBML model.", exists=True, dir_okay=False)],
    start: Annotated[float, typer.Option(help="Start time.")],
    duration: Annotated[float, typer.Option(help="Duration.")],
    points: Annotated[int, typer.Option(help="Number of output points.")],
    wait: Wait = False,
    download: Download = None,
    extract: Extract = False,
    poll: Poll = 5.0,
    wait_timeout: WaitTimeout = None,
) -> None:
    """Run an SBML model with COPASI."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        sim = s.submit_copasi(sbml, start=start, duration=duration, points=points)
        if not wait:
            emit(settings.output, sim)
            return
        _finish_job(
            ctx, s, sim.simulation_database_id, poll=poll, wait_timeout=wait_timeout, download=download, extract=extract
        )


@curated_app.command("tellurium")
@claims("curated tellurium", "run-tellurium")
@handled
def curated_tellurium(
    ctx: typer.Context,
    sbml: Annotated[Path, typer.Argument(help="The SBML model.", exists=True, dir_okay=False)],
    start: Annotated[float, typer.Option(help="Start time.")],
    end: Annotated[float, typer.Option(help="End time.")],
    points: Annotated[int, typer.Option(help="Number of output points.")],
    wait: Wait = False,
    download: Download = None,
    extract: Extract = False,
    poll: Poll = 5.0,
    wait_timeout: WaitTimeout = None,
) -> None:
    """Run an SBML model with Tellurium."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        sim = s.submit_tellurium(sbml, start=start, end=end, points=points)
        if not wait:
            emit(settings.output, sim)
            return
        _finish_job(
            ctx, s, sim.simulation_database_id, poll=poll, wait_timeout=wait_timeout, download=download, extract=extract
        )


# -- jobs ---------------------------------------------------------------------------------------------------------


@app.command()
@claims("status", "get-simulation-status", "get-simulations-status-batch")
@handled
def status(
    ctx: typer.Context,
    simulation_ids: Annotated[list[int], typer.Argument(help="One or more simulation ids.")],
) -> None:
    """Job state of one simulation, or of several in one call. "submitting" means no SLURM job yet."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        if len(simulation_ids) == 1:
            sid = simulation_ids[0]
            emit(settings.output, _state_record(sid, s.status(sid)))
            return
        runs = {r.sim_id: r for r in s.statuses(simulation_ids)}
    rows = [
        _state_record(sid, JobState.of(runs[sid]) if sid in runs else JobState("submitting")) for sid in simulation_ids
    ]
    emit(settings.output, rows, ["simulation_id", "status", "slurmjobid", "start_time", "end_time", "error_message"])


@app.command()
@claims("wait")
@handled
def wait(
    ctx: typer.Context,
    simulation_ids: Annotated[list[int], typer.Argument(help="One or more simulation ids.")],
    poll: Poll = 5.0,
    wait_timeout: WaitTimeout = None,
) -> None:
    """Wait until each simulation finishes; exit 1 unless all completed."""
    settings = _settings(ctx)
    rows = []
    with make_session(settings) as s:
        for sid in simulation_ids:
            state = s.wait(sid, poll=poll, timeout=wait_timeout, on_update=_progress(settings, f"simulation {sid}"))
            rows.append(_state_record(sid, state))
    emit(settings.output, rows if len(rows) > 1 else rows[0])
    if any(r["status"] != "completed" for r in rows):
        raise typer.Exit(EXIT_JOB)


@app.command()
@claims("results", "get-simulation-results-file")
@handled
def results(
    ctx: typer.Context,
    simulation_id: Annotated[int, typer.Argument(help="The simulation id.")],
    out: Annotated[
        Path | None, typer.Option("--out", "-O", help="Write the zip here (a file, or a directory).")
    ] = None,
    extract: Annotated[Path | None, typer.Option(help="Unpack the archive into this directory instead.")] = None,
) -> None:
    """Fetch a finished simulation's results archive."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        if extract is not None:
            files = s.extract(simulation_id, extract)
        else:
            files = [s.download(simulation_id, out if out is not None else Path.cwd())]
    emit(settings.output, {"simulation_id": simulation_id, "files": [str(f) for f in files]})


@app.command("build-status")
@claims("build-status", "get-simulator-build-status")
@handled
def build_status(
    ctx: typer.Context,
    simulator_id: Annotated[int, typer.Argument(help="The simulator id (from a submission's simulator_database_id).")],
    wait: Wait = False,
    poll: Poll = 5.0,
    wait_timeout: WaitTimeout = None,
) -> None:
    """State of a simulator's container build."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        if wait:
            state = s.wait_build(
                simulator_id, poll=poll, timeout=wait_timeout, on_update=_progress(settings, f"build {simulator_id}")
            )
        else:
            state = s.build_status(simulator_id)
    rec = _state_record(simulator_id, state)
    rec["simulator_id"] = rec.pop("simulation_id")
    emit(settings.output, rec)
    if wait and not state.ok:
        raise typer.Exit(EXIT_JOB)


# -- the spec -----------------------------------------------------------------------------------------------------


def bundled_spec() -> dict[str, Any]:
    """The OpenAPI document this client was generated from."""
    text = importlib.resources.files("compose_api_client").joinpath("openapi.json").read_text()
    return dict(json.loads(text))


def fetch_spec(settings: Settings) -> dict[str, Any]:
    """The live service's OpenAPI document. Tests replace this."""
    r = httpx.get(f"{settings.url.rstrip('/')}/openapi.json", timeout=settings.timeout)
    r.raise_for_status()
    return dict(r.json())


def operations(spec: dict[str, Any]) -> dict[str, str]:
    """operationId -> "METHOD /path"."""
    ops = {}
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if isinstance(op, dict) and "operationId" in op:
                ops[op["operationId"]] = f"{method.upper()} {path}"
    return ops


@app.command()
@claims("openapi")
@handled
def openapi(
    ctx: typer.Context,
    server: Annotated[bool, typer.Option(help="Fetch the live service's /openapi.json instead.")] = False,
    diff: Annotated[
        bool, typer.Option(help="Compare this client's operations with the live service's; exit 1 on skew.")
    ] = False,
) -> None:
    """The OpenAPI document: this client's (default) or the service's; --diff reports skew between them."""
    settings = _settings(ctx)
    if not (server or diff):
        emit(Output.JSON, bundled_spec())
        return
    live = fetch_spec(settings)
    if not diff:
        emit(Output.JSON, live)
        return
    mine, theirs = operations(bundled_spec()), operations(live)
    report = {
        "client_version": bundled_spec().get("info", {}).get("version"),
        "service_version": live.get("info", {}).get("version"),
        "only_in_client": sorted(set(mine) - set(theirs)),
        "only_in_service": sorted(set(theirs) - set(mine)),
        "moved": sorted(op for op in set(mine) & set(theirs) if mine[op] != theirs[op]),
    }
    emit(settings.output, report)
    if report["only_in_client"] or report["only_in_service"] or report["moved"]:
        raise typer.Exit(EXIT_JOB)


def main() -> None:
    app()
