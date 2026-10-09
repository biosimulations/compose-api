"""``compose-api``: the command line for compose-api (docs/plan-cli.md, step C).

Every API operation is claimed by exactly one command (``@claims``); ``tests/client/test_cli.py`` fails when the
spec has an operation no command claims, or a command claims one the spec lacks.

Exit codes: 0 success; 1 the job ended other than completed; 2 usage; 3 API error; 4 not found; 5 a wait timed out;
130 interrupted.
"""

from __future__ import annotations

import dataclasses
import datetime
import functools
import importlib.resources
import inspect
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypeVar

import click
import httpx
import typer

from compose_api_client.cli.render import Output, emit, err, event_line, lines, resolve, span_tree
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


LOGIN_HINT = "Run compose-api auth login to sign in again, or compose-api auth logout to continue anonymously."


def _login_failed(exc: Exception) -> typer.Exit:
    """A stored login that cannot be used: exit 3 with a way back, never a silent anonymous request."""
    message = str(exc)
    typer.echo(message, err=True)
    if "auth login" not in message:
        typer.echo(LOGIN_HINT, err=True)
    return typer.Exit(EXIT_API)


def make_session(settings: Settings) -> ComposeSession:
    """The session every command uses. Tests replace this to inject a transport.

    Credentials: ``--token`` / ``COMPOSE_API_TOKEN``, else the stored login for ``--url`` (renewed before each
    request, so long-running commands keep working), else anonymous when there is no stored login at all.
    """
    from compose_api_client.cli.auth import LoginError, StoredAuth, access_token

    try:
        token = settings.token if settings.token is not None else access_token(settings.url)
        session = ComposeSession(settings.url, token=token, timeout=settings.timeout)
        if settings.token is None and token is not None:
            try:
                session.client.get_httpx_client().auth = StoredAuth(settings.url)
            except BaseException:
                session.close()
                raise
    except LoginError as exc:
        raise _login_failed(exc) from None
    return session


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
datasets_app = typer.Typer(help="The files runs produced.", no_args_is_help=True)
app.add_typer(datasets_app, name="datasets")
simulations_app = typer.Typer(help="Find simulations and their ids.", no_args_is_help=True)
app.add_typer(simulations_app, name="simulations")
auth_app = typer.Typer(
    help="Sign in through BioSimulations, sign out, and see who the service sees.", no_args_is_help=True
)
app.add_typer(auth_app, name="auth")


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
    if token is not None and not token.strip():
        # An empty token would otherwise mean anonymous here and "use the stored login" elsewhere.
        raise typer.BadParameter("must not be empty; omit it to use a stored login", param_hint="--token")
    ctx.obj = Settings(url=url, timeout=timeout, output=output, token=token, verbose=verbose, quiet=quiet)
    if verbose:
        import logging

        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logging.getLogger("httpx").setLevel(logging.INFO)


def _settings(ctx: click.Context) -> Settings:
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


#: ``--json`` on every command: the same as ``--output json`` before the command name.
JSON_OPTION = inspect.Parameter(
    "json_output",
    inspect.Parameter.KEYWORD_ONLY,
    default=False,
    annotation=Annotated[bool, typer.Option("--json", help="Print JSON (the same as --output json).")],
)


def handled(fn: F) -> F:
    """Map exceptions to a message on stderr and the documented exit code (``--verbose`` re-raises), and give the
    command a ``--json`` option. Every command goes through here, so every command's help shows it."""

    @functools.wraps(fn)
    def wrapper(*args: Any, json_output: bool = False, **kwargs: Any) -> Any:
        # Typer passes a plain click.Context, so test for that: a typer.Context check never matched, and the
        # --verbose re-raise below never saw the real settings.
        ctx = next((a for a in args if isinstance(a, click.Context)), kwargs.get("ctx"))
        if json_output and isinstance(ctx, click.Context):
            root = ctx.find_root()
            root.obj = dataclasses.replace(_settings(ctx), output=Output.JSON)
        settings = _settings(ctx) if isinstance(ctx, click.Context) else Settings()
        try:
            return fn(*args, **kwargs)
        except typer.Exit:
            raise
        except (Exception, KeyboardInterrupt) as e:
            from compose_api_client.cli.auth import LoginError

            if isinstance(e, LoginError):
                raise _login_failed(e) from None
            code = _report(e, settings)
            if code is None or settings.verbose:
                raise
            raise typer.Exit(code) from None

    signature = inspect.signature(fn, eval_str=True)
    wrapper.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=[*signature.parameters.values(), JSON_OPTION]
    )
    wrapper.__annotations__ = {**fn.__annotations__, "json_output": JSON_OPTION.annotation}
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


# -- finding simulations ------------------------------------------------------------------------------------------

SIMULATION_COLUMNS = ["simulation_id", "created_at", "simulator_id", "simulator", "status", "slurm_job_id", "end_time"]
_UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_since(value: str) -> datetime.datetime:
    """``30m``, ``6h``, ``2d`` or ``1w`` ago, or an ISO 8601 time (UTC if it names no zone)."""
    text = value.strip()
    if text[:-1].isdigit() and text[-1:] in _UNITS:
        return datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(seconds=int(text[:-1]) * _UNITS[text[-1]])
    try:
        moment = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise typer.BadParameter(f"{value!r}: use 30m, 6h, 2d, 1w, or an ISO time") from e
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.UTC)


@simulations_app.command("list")
@claims("simulations list", "list-simulations")
@handled
def simulations_list(
    ctx: typer.Context,
    status: Annotated[
        str | None, typer.Option(help="Only this state: submitting, running, completed, failed, timeout, ...")
    ] = None,
    simulator: Annotated[
        str | None, typer.Option(help="Only this prebuilt simulator (name), or a container-definition hash prefix.")
    ] = None,
    since: Annotated[
        str | None, typer.Option(help="Only those created since: 30m, 6h, 2d, 1w, or an ISO time.")
    ] = None,
    limit: Annotated[int, typer.Option(help="At most this many.")] = 50,
    offset: Annotated[int, typer.Option(help="Skip this many (for the next page).")] = 0,
) -> None:
    """Simulations you can read, newest first, each with its latest SLURM job. The ids are what every other command
    takes."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        page = s.simulations(
            status=status,
            simulator=simulator,
            since=parse_since(since) if since else None,
            limit=limit,
            offset=offset,
        )
    rows = [sim.to_dict() for sim in page.simulations]
    shown = f"{offset + 1}-{offset + len(rows)}" if rows else "0"
    emit(settings.output, rows, SIMULATION_COLUMNS, title=f"simulations {shown} of {page.total}")


@simulations_app.command("show")
@claims("simulations show", "get-simulation")
@handled
def simulations_show(
    ctx: typer.Context, simulation_id: Annotated[int, typer.Argument(help="The simulation id.")]
) -> None:
    """One simulation: its simulator, its latest SLURM job, and how many events and datasets its run recorded."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        emit(settings.output, s.simulation(simulation_id).to_dict())


# -- events and traces --------------------------------------------------------------------------------------------


@app.command()
@claims("events", "get-simulation-events")
@handled
def events(
    ctx: typer.Context,
    simulation_id: Annotated[int, typer.Argument(help="The simulation id.")],
    follow: Annotated[
        bool, typer.Option("--follow", "-f", help="Keep printing new events until the job has finished.")
    ] = False,
    level: Annotated[str | None, typer.Option(help="Only events at this level: debug, info, warning, error.")] = None,
    event: Annotated[str | None, typer.Option(help="Only events with this name, e.g. job.end.")] = None,
    poll: Poll = 5.0,
) -> None:
    """A simulation's events: from the API, the job script and the simulator's engine. JSON output is JSON lines."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        for record in s.iter_events(simulation_id, follow=follow, poll=poll, level=level, event=event):
            event_line(settings.output, record.to_dict())


@app.command()
@claims("trace", "get-simulation-trace", "get-simulation-trace-chrome")
@handled
def trace(
    ctx: typer.Context,
    simulation_id: Annotated[int, typer.Argument(help="The simulation id.")],
    chrome: Annotated[
        Path | None,
        typer.Option(help="Save the trace as a Chrome Trace Event file instead; open it in ui.perfetto.dev."),
    ] = None,
) -> None:
    """A simulation's spans as a tree, each with its own events; or, with --chrome, a file for Perfetto."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        if chrome is not None:
            chrome.write_text(json.dumps(s.trace_chrome(simulation_id)))
            emit(settings.output, {"simulation_id": simulation_id, "files": [str(chrome)]})
            return
        tree = s.trace(simulation_id).to_dict()
    if resolve(settings.output) is Output.JSON:
        emit(settings.output, tree)
    elif not tree.get("roots"):
        err.print(f"simulation {simulation_id} has no spans recorded (yet)")
    else:
        span_tree(tree["roots"])


# -- datasets -----------------------------------------------------------------------------------------------------

DATASET_COLUMNS = ["id", "simulation_id", "path", "kind", "size_bytes", "available"]


@datasets_app.command("list")
@claims("datasets list", "list-datasets")
@handled
def datasets_list(
    ctx: typer.Context,
    simulation: Annotated[int | None, typer.Option("--sim", help="Only this simulation's datasets.")] = None,
    kind: Annotated[str | None, typer.Option(help="Only this kind: results, table, figure, archive, ...")] = None,
    q: Annotated[str | None, typer.Option("--match", help="Only paths or names containing this.")] = None,
    missing: Annotated[bool, typer.Option(help="List datasets whose file is gone instead.")] = False,
    limit: Annotated[int, typer.Option(help="At most this many.")] = 100,
) -> None:
    """The files runs produced: one simulation's, or every one you may read, newest simulations first."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        page = s.datasets(simulation_id=simulation, kind=kind, q=q, available=not missing, limit=limit)
    rows = [d.to_dict() for d in page.datasets]
    emit(settings.output, rows, DATASET_COLUMNS, title=f"{len(rows)} of {page.total} datasets")


@datasets_app.command("show")
@claims("datasets show", "get-dataset")
@handled
def datasets_show(ctx: typer.Context, dataset_id: Annotated[str, typer.Argument(help="The dataset id.")]) -> None:
    """Everything recorded about one dataset."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        emit(settings.output, s.dataset(dataset_id).to_dict())


@datasets_app.command("get")
@claims("datasets get", "get-dataset-content")
@handled
def datasets_get(
    ctx: typer.Context,
    dataset_id: Annotated[str, typer.Argument(help="The dataset id.")],
    out: Annotated[
        Path | None, typer.Option("--out", "-O", help="Write it here (a file, or a directory). Default: here.")
    ] = None,
) -> None:
    """Download a dataset's file."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        path = s.download_dataset(dataset_id, out if out is not None else Path.cwd())
    emit(settings.output, {"dataset_id": dataset_id, "files": [str(path)]})


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


# -- identity -------------------------------------------------------------------------------------------------------


@auth_app.command("login")
@handled
def auth_login(ctx: typer.Context) -> None:
    """Sign in through BioSimulations, then authorize the CLI separately with Auth0 PKCE."""
    from compose_api_client.cli import auth

    settings = _settings(ctx)
    env = auth.environment_for(settings.url)
    if env is None:
        typer.echo("No Auth0 application for this URL; use --token.", err=True)
        raise typer.Exit(EXIT_USAGE)

    def notify(message: str) -> None:
        typer.echo(message, err=True)

    try:
        _portal_login(settings, notify)
    except typer.Exit:
        raise
    except (KeyboardInterrupt, click.Abort):
        notify("Login cancelled. No new credentials were saved.")
        raise typer.Exit(EXIT_INTERRUPT) from None
    except TimeoutError:
        notify("CLI authorization timed out. No new credentials were saved; run compose-api auth login again.")
        raise typer.Exit(EXIT_TIMEOUT) from None
    except auth.LoginError as exc:
        notify(str(exc))
        raise typer.Exit(EXIT_API) from None
    except Exception:
        # Do not expose provider/API responses or token-bearing exception objects, even with --verbose.
        notify("Login could not be confirmed or saved. Check API /auth/me availability and credential storage.")
        raise typer.Exit(EXIT_API) from None


def _portal_login(settings: Settings, notify: Callable[[str], None]) -> None:
    from compose_api_client.cli import auth

    env = auth.environment_for(settings.url)
    if env is None:
        raise typer.Exit(EXIT_USAGE)
    auth.open_browser(auth.PORTAL_URL, notify)
    if settings.token:
        _confirm_supplied_token(settings)
        notify("The API confirmed your supplied token. No browser credentials were saved.")
        return
    if _stored_login_confirmed(settings, notify):
        notify("Already authenticated; the API confirmed the stored access token.")
        return
    notify("Sign in at BioSimulations (or choose Sign Up and finish any required verification).")
    notify("Website login alone does not authenticate this CLI. Next, authorize the Compose API native client.")
    if not typer.confirm("Ready to continue to CLI authorization?", default=False, err=True):
        raise click.Abort  # declining is a cancellation: the same message and exit 130 as Ctrl-C
    tokens = auth.login_interactive_tokens(env, notify)
    with ComposeSession(settings.url, token=tokens.access_token, timeout=min(settings.timeout, 10)) as session:
        identity = session.whoami()
    if identity.issuer != f"{auth.ISSUER_URL}/" or env.audience not in identity.audience:
        raise auth.LoginError("The API reported an incompatible issuer or audience. No credentials were saved.")
    tokens.subject = identity.subject
    auth.save(settings.url, tokens)
    notify("Authenticated: Compose API accepted the access token; credentials saved securely.")


def _confirm_supplied_token(settings: Settings) -> None:
    from compose_api_client.cli import auth

    with make_session(settings) as session:
        try:
            session.whoami()
        except ComposeApiError as exc:
            raise auth.LoginError(
                f"The API did not accept the supplied token (HTTP {exc.status_code}). Nothing was saved."
            ) from None


def _stored_login_confirmed(settings: Settings, notify: Callable[[str], None]) -> bool:
    """Whether the API accepts the current stored login; False when there is none, or it is unusable or rejected."""
    from compose_api_client.cli import auth

    try:
        existing = auth.access_token(settings.url)
    except auth.LoginError as exc:
        notify(f"Stored login could not be used: {exc}")
        return False  # an expired local login can be replaced by a new verified login
    if not existing:
        return False
    try:
        with ComposeSession(settings.url, token=existing, timeout=min(settings.timeout, 10)) as session:
            session.whoami()
    except ComposeApiError as exc:
        if exc.status_code != 401:
            raise
        return False
    return True


@auth_app.command("signup")
@handled
def auth_signup() -> None:
    """Open BioSimulations registration; this does not establish a CLI session."""
    from compose_api_client.cli import auth

    auth.open_browser(auth.PORTAL_URL, lambda message: typer.echo(message, err=True))
    typer.echo(
        "Choose Sign Up at BioSimulations and complete any required verification. "
        "Then run compose-api auth login. No CLI credentials were obtained or saved.",
        err=True,
    )


@auth_app.command("logout")
@handled
def auth_logout(ctx: typer.Context) -> None:
    """Remove local credentials and attempt refresh-token revocation; browser sessions remain signed in."""
    from compose_api_client.cli import auth

    try:
        revoked = auth.logout(_settings(ctx).url)
    except Exception:
        typer.echo("Could not clear the credential file; check its permissions and format.", err=True)
        raise typer.Exit(EXIT_API) from None
    message = "Local credentials removed; refresh-token revocation completed or was not needed."
    if not revoked:
        message = "Local credentials removed; refresh-token revocation could not be confirmed."
    typer.echo(message + " Browser sessions and issued access tokens may remain valid.", err=True)


@auth_app.command("whoami")
@claims("auth whoami", "get-auth-me")
@handled
def auth_whoami(ctx: typer.Context) -> None:
    """Who the service sees: the identity behind --token, COMPOSE_API_TOKEN, or auth login."""
    with make_session(_settings(ctx)) as s:
        emit(_settings(ctx).output, s.whoami())


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
