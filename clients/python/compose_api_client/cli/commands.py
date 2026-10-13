"""``compose-api``: the command line for compose-api (docs/plan-cli.md, step C).

Every API operation is claimed by exactly one command (``@claims``); ``tests/client/test_cli.py`` fails when the
spec has an operation no command claims, or a command claims one the spec lacks.

Exit codes: 0 success; 1 the job ended other than completed; 2 usage; 3 API error; 4 not found; 5 a wait timed out;
130 interrupted.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import functools
import importlib.metadata
import importlib.resources
import inspect
import json
import math
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypeAlias, TypeVar

import click
import httpx
import typer

from compose_api_client.cli.render import (
    Output,
    emit,
    err,
    event_line,
    lines,
    printable,
    printable_lines,
    resolve,
    span_tree,
)
from compose_api_client.ext import (
    DEFAULT_URL,
    ApiTimeout,
    BadRequest,
    CliError,
    ComposeApiError,
    ComposeSession,
    EnvironmentToken,
    ExitCode,
    JobState,
    NotFound,
)
from compose_api_client.ext.credentials import TOKEN_ENV_VAR
from compose_api_client.types import Unset

try:
    __version__ = importlib.metadata.version("compose-api-client")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

PROG = "compose-api"
EXIT_JOB = int(ExitCode.FAILURE)
EXIT_USAGE = int(ExitCode.USAGE)
EXIT_AUTH = int(ExitCode.AUTH_REQUIRED)
EXIT_FORBIDDEN = int(ExitCode.FORBIDDEN)
EXIT_NETWORK = int(ExitCode.NETWORK)
EXIT_CONFIG = int(ExitCode.CONFIG)
EXIT_TIMEOUT = int(ExitCode.WAIT_TIMEOUT)
EXIT_API = int(ExitCode.FAILURE)
EXIT_NOT_FOUND = int(ExitCode.FAILURE)
EXIT_INTERRUPT = int(ExitCode.CANCELLED)

CLAIMS: dict[str, str] = {}  # operationId -> command
F = TypeVar("F", bound=Callable[..., Any])
Handler: TypeAlias = Callable[[argparse.Namespace], int]
Subcommands: TypeAlias = "argparse._SubParsersAction[argparse.ArgumentParser]"


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
    profile: str | None = None
    timeout: float = 300.0
    output: Output = Output.AUTO
    token: str | None = None
    verbose: bool = False
    quiet: bool = False
    url_explicit: bool = False


def make_session(settings: Settings) -> ComposeSession:
    """The session every command uses. Tests replace this to inject a transport."""
    if settings.token is not None:
        return ComposeSession(settings.url, token=settings.token, timeout=settings.timeout)
    if TOKEN_ENV_VAR in os.environ:
        env_token = EnvironmentToken()
        from compose_api_client.profiles import canonical_api_base_url, load_profile

        loaded = load_profile(settings.profile).settings
        target_url = canonical_api_base_url(settings.url) if settings.url_explicit else loaded.api_base_url
        if settings.url_explicit and target_url != loaded.api_base_url:
            err.print(
                f"compose-api: note: --url ({target_url}) does not match profile {loaded.profile!r}"
                f" ({loaded.api_base_url}); calling anonymously without {TOKEN_ENV_VAR}",
                markup=False,
                highlight=False,
            )
            return ComposeSession(target_url, timeout=settings.timeout, ca_bundle=loaded.ca_bundle)
        err.print(
            f"compose-api: note: using {TOKEN_ENV_VAR} from the environment instead of a stored session",
            markup=False,
            highlight=False,
        )
        return ComposeSession(
            target_url,
            tokens=env_token,
            timeout=settings.timeout,
            ca_bundle=loaded.ca_bundle,
        )
    return ComposeSession(settings.url, timeout=settings.timeout)


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
sedml_app = typer.Typer(help="Run SED-ML archives on several solvers and compare them.", no_args_is_help=True)
comparisons_app = typer.Typer(
    help="A SED-ML task's runs on several solvers, and how they compare.", no_args_is_help=True
)
app.add_typer(simulations_app, name="simulations")
environments_app = typer.Typer(
    help="The environments documents run in, and the process interfaces each provides.", no_args_is_help=True
)
app.add_typer(environments_app, name="environments")
app.add_typer(sedml_app, name="sedml")
app.add_typer(comparisons_app, name="comparisons")
biomodels_app = typer.Typer(help="EBI BioModels: search, describe, download, run.", no_args_is_help=True)
biosimulations_app = typer.Typer(
    help="biosimulations.org projects: search, describe, download, run.", no_args_is_help=True
)
app.add_typer(biomodels_app, name="biomodels")
app.add_typer(biosimulations_app, name="biosimulations")
suites_app = typer.Typer(help="Regression and reproducibility suites of SED-ML models.", no_args_is_help=True)
app.add_typer(suites_app, name="suites")
auth_app = typer.Typer(help="Sign up, sign in, check or end a session.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")
config_app = typer.Typer(help="Inspect the CLI configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")


@app.callback()
def root(
    ctx: typer.Context,
    url: Annotated[str | None, typer.Option(envvar="COMPOSE_API_URL", help="Service base URL.")] = None,
    profile: Annotated[
        str | None,
        typer.Option("--profile", envvar="COMPOSE_API_CLI_PROFILE", help="Profile to use (default: production)."),
    ] = None,
    timeout: Annotated[float, typer.Option(envvar="COMPOSE_API_TIMEOUT", help="HTTP timeout, seconds.")] = 300.0,
    output: Annotated[
        Output,
        typer.Option("--output", "-o", envvar="COMPOSE_API_OUTPUT", help="auto: table on a terminal, else json."),
    ] = Output.AUTO,
    token_removed: Annotated[
        str | None,
        typer.Option("--token", hidden=True, help="Removed: use auth login or COMPOSE_API_TOKEN."),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log HTTP requests; tracebacks on errors.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="No progress lines.")] = False,
) -> None:
    if token_removed is not None:
        err.print(
            "compose-api: error: --token is no longer supported; use `compose-api auth login`, or set"
            f" {TOKEN_ENV_VAR} for automation",
            markup=False,
            highlight=False,
        )
        raise typer.Exit(EXIT_USAGE)
    ctx.obj = Settings(
        url=url if url is not None else DEFAULT_URL,
        profile=profile,
        timeout=timeout,
        output=output,
        verbose=verbose,
        quiet=quiet,
        url_explicit=url is not None,
    )
    if verbose:
        import logging

        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logging.getLogger("httpx").setLevel(logging.INFO)


def _settings(ctx: click.Context) -> Settings:
    obj = ctx.find_root().obj
    return obj if isinstance(obj, Settings) else Settings()


def _emit_envelope(enabled: bool, category: str, message: str, code: int) -> int:
    if enabled:
        print(json.dumps({"error": {"category": category, "message": message, "exit_code": int(code)}}))
    return int(code)


def _report_api_error(e: ComposeApiError, *, emit_envelope: bool) -> int:
    msg = _detail(e.detail) if e.detail is not None else e.message
    if isinstance(e, NotFound):
        err.print(f"[red]not found[/]: {printable_lines(msg)}", markup=True, highlight=False)
    elif isinstance(e, BadRequest):
        err.print(f"[red]rejected ({e.status_code})[/]: {printable_lines(msg)}", markup=True, highlight=False)
        for v in e.violations[:5]:
            rendered = v if isinstance(v, str) else json.dumps(v, default=str)
            err.print(f"  - {printable(rendered)}", markup=False, highlight=False)
    else:
        err.print(f"[red]compose-api error ({e.status_code})[/]: {printable_lines(msg)}", markup=True, highlight=False)
    return _emit_envelope(emit_envelope, e.category, msg, int(e.exit_code))


def _report(e: BaseException, settings: Settings, *, emit_envelope: bool = False) -> int | None:
    """Print ``e`` to stderr and return its exit code; ``None`` for an exception the CLI does not own."""
    if isinstance(e, KeyboardInterrupt):
        err.print("[yellow]interrupted[/]")
        return EXIT_INTERRUPT
    if isinstance(e, ComposeApiError):
        return _report_api_error(e, emit_envelope=emit_envelope)
    if isinstance(e, ApiTimeout):
        err.print(f"[red]timed out[/]: {printable_lines(str(e))}", markup=True, highlight=False)
        return _emit_envelope(emit_envelope, e.category, e.message, int(e.exit_code))
    if isinstance(e, CliError):
        err.print(f"compose-api: error: {printable_lines(e.message)}", markup=False, highlight=False)
        return _emit_envelope(emit_envelope, e.category, e.message, int(e.exit_code))
    if isinstance(e, httpx.HTTPError):
        msg = f"cannot reach {settings.url}: {e}"
        err.print(f"[red]cannot reach {printable(settings.url)}[/]: {printable_lines(str(e))}", highlight=False)
        return _emit_envelope(emit_envelope, "network", msg, EXIT_NETWORK)
    if isinstance(e, (FileNotFoundError, IsADirectoryError)):
        err.print(f"[red]{printable_lines(str(e))}[/]", highlight=False)
        return _emit_envelope(emit_envelope, "usage", str(e), EXIT_USAGE)
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
            code = _report(e, settings, emit_envelope=bool(json_output))
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


@environments_app.command("list")
@claims("environments list", "list-environments")
@handled
def environments_list(ctx: typer.Context) -> None:
    """Environments: the `--simulator` to run in each, its image, and whether its manifest is current."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        envs = s.environments()
    rows = [
        {
            "name": e.name,
            "simulator": e.simulator,
            "components": e.components,
            "errors": e.errors,
            "stale": e.stale,
            "image": e.image,
        }
        for e in envs
    ]
    emit(
        settings.output,
        rows if settings.output is not Output.JSON else [e.to_dict() for e in envs],
        ["name", "simulator", "components", "errors", "stale", "image"],
    )


@app.command()
@claims("catalog", "list-registry-entries")
@handled
def catalog(ctx: typer.Context) -> None:
    """The catalog: every registry entry with its curation level, and the environments that provide its classes.

    Discovery and trust, not runnability: most `listed` entries are in no environment (docs/plan-sedml.md)."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        entries = s.catalog()
    rows = [
        {
            "id": e.id,
            "level": str(e.level),
            "package": e.package,
            "pin": e.version or (e.commit[:12] if isinstance(e.commit, str) else None),
            "environments": ", ".join(
                f"{x.name} ({x.components})" for x in (e.environments if isinstance(e.environments, list) else [])
            )
            or None,
        }
        for e in entries
    ]
    emit(
        settings.output,
        rows if settings.output is not Output.JSON else [e.to_dict() for e in entries],
        ["id", "level", "package", "pin", "environments"],
    )


@app.command()
@claims("solvers", "list-solvers")
@handled
def solvers(ctx: typer.Context) -> None:
    """The solvers SED-ML runs can use: each one's class, environment, KiSAO algorithms (default first)."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        found = s.solvers()
    rows = [
        {
            "id": x.id,
            "name": x.name,
            "environment": x.environment,
            "algorithms": ", ".join(x.algorithms),
            "address": x.address,
        }
        for x in found
    ]
    emit(
        settings.output,
        rows if settings.output is not Output.JSON else [x.to_dict() for x in found],
        ["id", "name", "environment", "algorithms", "address"],
    )


@environments_app.command("manifest")
@claims("environments manifest", "get-environment-manifest")
@handled
def environments_manifest(
    ctx: typer.Context, name: Annotated[str, typer.Argument(help="The environment, e.g. registry_env.")]
) -> None:
    """An environment's interface manifest: its steps and processes, their config schemas and ports.

    `--output json` prints the manifest itself (pbg-interfaces/1), which other tools read as it is."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        manifest = s.environment_manifest(name)
    if settings.output is Output.JSON:
        emit(Output.JSON, manifest.to_dict())
        return
    rows = [
        {
            "address": c.address,
            "kind": c.kind,
            "dynamic_ports": c.dynamic_ports,
            "entry": c.registry_entry.id if c.registry_entry else None,
        }
        for c in manifest.components
    ]
    emit(settings.output, rows, ["address", "kind", "dynamic_ports", "entry"])


@environments_app.command("headers")
@claims("environments headers", "get-environment-headers")
@handled
def environments_headers(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The environment, e.g. registry_env.")],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write one <module>.pbl per module into this directory.")
    ] = None,
) -> None:
    """An environment's interfaces as .pblang header files: what a composite imports (`import module.{Name};`).

    Prints every module's file, or writes them into `--out`; `--output json` prints them with each class's
    declaration."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        headers = s.environment_headers(name)
    if settings.output is Output.JSON:
        emit(Output.JSON, headers.to_dict())
    elif out is not None:
        out.mkdir(parents=True, exist_ok=True)
        for m in headers.modules:
            (out / f"{m.module}.pbl").write_text(m.text)
        print(f"wrote {len(headers.modules)} header file(s) to {out}", file=sys.stderr)
    else:
        print("\n".join(m.text for m in headers.modules), end="")


def _emit_image_status(settings: Settings, status: Any) -> None:
    """An image status: one row per image record (the available one first), or the status itself as JSON."""
    if settings.output is Output.JSON:
        emit(Output.JSON, status.to_dict())
        return
    build = status.build if not isinstance(status.build, Unset) and status.build is not None else None
    print(
        f"simulator {status.simulator_id} ({status.container_def_hash[:12]}): {status.state}"
        + (f"; newest build run {build.database_id} {build.status} ({build.backend})" if build else "")
    )
    rows = [
        {
            "id": i.database_id,
            "kind": i.kind,
            "available": i.available,
            "size": i.size_bytes,
            "digest": (i.digest or "")[:19],
            "run": i.hpcrun_id,
            "location": i.location,
        }
        for i in (status.images if isinstance(status.images, list) else [])
    ]
    if rows:
        emit(settings.output, rows, ["id", "kind", "available", "size", "digest", "run", "location"])


@environments_app.command("images")
@claims("environments images", "get-environment-images")
@handled
def environments_images(
    ctx: typer.Context, name: Annotated[str, typer.Argument(help="The environment, e.g. registry_env.")]
) -> None:
    """Whether an environment's current image is built: its image records and its newest build run."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        _emit_image_status(settings, s.environment_images(name))


@environments_app.command("build")
@claims("environments build", "build-environment")
@handled
def environments_build(
    ctx: typer.Context, name: Annotated[str, typer.Argument(help="The environment, e.g. registry_env.")]
) -> None:
    """Make an environment's current image available: pulled or built unless it is, joining a build under way.

    Returns at once; `environments images` follows the build."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        _emit_image_status(settings, s.build_environment(name))


@simulators_app.command("images")
@claims("simulators images", "get-simulator-images")
@handled
def simulators_images(
    ctx: typer.Context, simulator_id: Annotated[int, typer.Argument(help="The simulator's id.")]
) -> None:
    """Whether a simulator's image is built: its image records and its newest build run."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        _emit_image_status(settings, s.simulator_images(simulator_id))


@simulators_app.command("build")
@claims("simulators build", "build-simulator")
@handled
def simulators_build(
    ctx: typer.Context, simulator_id: Annotated[int, typer.Argument(help="The simulator's id.")]
) -> None:
    """Make a simulator's image available: pulled or built unless it is, joining a build under way."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        _emit_image_status(settings, s.build_simulator(simulator_id))


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
    tag: Annotated[
        list[str] | None, typer.Option("--tag", "-t", help="A tag to find the run by later (repeatable).")
    ] = None,
    description: Annotated[str | None, typer.Option(help="What the run is for.")] = None,
    wait: Wait = False,
    download: Download = None,
    extract: Extract = False,
    poll: Poll = 5.0,
    wait_timeout: WaitTimeout = None,
) -> None:
    """Submit a simulation. Prints its ids; with --wait, its final state (and the files, with --download)."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        sim = s.submit(
            document, simulator=simulator, interval=interval, batch=batch, tags=tag or (), description=description
        )
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

SIMULATION_COLUMNS = [
    "simulation_id", "created_at", "simulator_id", "simulator", "status", "slurm_job_id", "end_time", "tags",
]  # fmt: skip
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


def parse_labels(values: list[str] | None) -> dict[str, str]:
    """``key:value`` options as a mapping; the server says which keys exist."""
    parsed: dict[str, str] = {}
    for value in values or []:
        key, sep, rest = value.partition(":")
        if not sep or not key or not rest:
            raise typer.BadParameter(f"{value!r}: use key:value, e.g. source:biomodels")
        parsed[key] = rest
    return parsed


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
    label: Annotated[
        list[str] | None,
        typer.Option(help="Only those with this label, key:value, e.g. source:biomodels (repeatable, all must match)."),
    ] = None,
    tag: Annotated[
        list[str] | None, typer.Option(help="Only those with this tag (repeatable, all must match).")
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
            labels=parse_labels(label),
            tags=tag or (),
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


@datasets_app.command("file")
@claims("datasets file", "get-dataset-file")
@handled
def datasets_file(
    ctx: typer.Context,
    dataset_id: Annotated[str, typer.Argument(help="The dataset id (a directory dataset: a results bundle or zarr).")],
    subpath: Annotated[str, typer.Argument(help="The file inside it, e.g. .zattrs or u/0.0.")],
    out: Annotated[
        Path | None, typer.Option("--out", "-O", help="Write it here (a file, or a directory). Default: here.")
    ] = None,
) -> None:
    """Download one file from inside a directory dataset."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        path = s.download_dataset_file(dataset_id, subpath, out if out is not None else Path.cwd())
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


@config_app.command("show")
@handled
def config_show(ctx: typer.Context) -> None:
    """Print the effective profile and where each value came from."""
    from compose_api_client.cli import auth_commands

    settings = _settings(ctx)
    ns = argparse.Namespace(profile=settings.profile, json=resolve(settings.output) is Output.JSON)
    code = auth_commands.show_config(ns)
    if code != 0:
        raise typer.Exit(code)


@auth_app.command("signup")
@handled
def auth_signup(
    ctx: typer.Context,
    provider: Annotated[str, typer.Option(help="Identity provider: email or google.")] = "email",
    device: Annotated[bool, typer.Option("--device", help="Sign in on another device (RFC 8628).")] = False,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Print the sign-in URL instead of opening it.")
    ] = False,
) -> None:
    """Create an account in the browser, then sign in."""
    from compose_api_client.cli import auth_commands

    if device and no_browser:
        raise typer.BadParameter("--device and --no-browser are mutually exclusive")
    settings = _settings(ctx)
    ns = argparse.Namespace(
        profile=settings.profile,
        provider=provider,
        device=device,
        no_browser=no_browser,
        json=resolve(settings.output) is Output.JSON,
    )
    code = auth_commands.signup(ns)
    if code != 0:
        raise typer.Exit(code)


@auth_app.command("login")
@handled
def auth_login(
    ctx: typer.Context,
    provider: Annotated[str | None, typer.Option(help="Identity provider: email or google.")] = None,
    device: Annotated[bool, typer.Option("--device", help="Sign in on another device (RFC 8628).")] = False,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Print the sign-in URL instead of opening it.")
    ] = False,
) -> None:
    """Sign in in the browser or with a device code."""
    from compose_api_client.cli import auth_commands

    if device and no_browser:
        raise typer.BadParameter("--device and --no-browser are mutually exclusive")
    settings = _settings(ctx)
    ns = argparse.Namespace(
        profile=settings.profile,
        provider=provider,
        device=device,
        no_browser=no_browser,
        json=resolve(settings.output) is Output.JSON,
    )
    code = auth_commands.login(ns)
    if code != 0:
        raise typer.Exit(code)


@auth_app.command("status")
@claims("auth status", "get-current-principal")
@handled
def auth_status(
    ctx: typer.Context,
    verify: Annotated[
        bool, typer.Option("--verify", help="Refresh if needed and confirm the identity with the API.")
    ] = False,
) -> None:
    """Show the stored session without contacting any server, unless --verify is given."""
    from compose_api_client.cli import auth_commands

    settings = _settings(ctx)
    ns = argparse.Namespace(
        profile=settings.profile,
        verify=verify,
        json=resolve(settings.output) is Output.JSON,
    )
    code = auth_commands.status(ns)
    if code != 0:
        raise typer.Exit(code)


@auth_app.command("logout")
@handled
def auth_logout(
    ctx: typer.Context,
    local_only: Annotated[
        bool, typer.Option("--local-only", help="Erase the local session without contacting Auth0.")
    ] = False,
) -> None:
    """Revoke the refresh token with Auth0 and erase the stored session."""
    from compose_api_client.cli import auth_commands

    settings = _settings(ctx)
    ns = argparse.Namespace(
        profile=settings.profile,
        local_only=local_only,
        json=resolve(settings.output) is Output.JSON,
    )
    code = auth_commands.logout(ns)
    if code != 0:
        raise typer.Exit(code)


_EPILOG = """\
exit status:
  0    success
  1    the API or command reported a failure
  2    usage error
  3    sign-in required, or the session has expired
  4    the API refused the request (forbidden)
  5    network failure or rate limit
  6    configuration, credential storage or protocol error
  7    a wait timed out
  130  cancelled

Profiles come from COMPOSE_API_CLI_* environment variables and config.toml in the user config directory;
`compose-api config show` prints the effective values and where each came from.
"""


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--profile",
        metavar="NAME",
        default=argparse.SUPPRESS,
        help="profile to use: production (default), local, or one defined in config.toml",
    )
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="write a machine-readable JSON object to stdout",
    )

    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Sign in to the Compose API and call it from the command line.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands_sub = parser.add_subparsers(title="commands", metavar="COMMAND", required=True)
    _add_config_commands(commands_sub, common)
    _add_auth_commands(commands_sub, common)
    _add_api_commands(commands_sub, common)
    return parser


def _add_config_commands(commands_sub: Subcommands, common: argparse.ArgumentParser) -> None:
    group = commands_sub.add_parser("config", parents=[common], help="inspect the CLI configuration")
    subcommands = group.add_subparsers(title="commands", metavar="COMMAND", required=True)
    show = subcommands.add_parser(
        "show",
        parents=[common],
        help="print the effective profile and where each value came from",
        description="Print the effective public profile and the source of each value. Profiles hold no secrets.",
    )
    show.set_defaults(handler=_dispatch_show_config)


def _add_auth_commands(commands_sub: Subcommands, common: argparse.ArgumentParser) -> None:
    group = commands_sub.add_parser("auth", parents=[common], help="sign up, sign in, check or end a session")
    subcommands = group.add_subparsers(title="commands", metavar="COMMAND", required=True)

    signup_cmd = subcommands.add_parser(
        "signup",
        parents=[common],
        help="create an account in the browser, then sign in",
        description="Open Auth0's hosted sign-up page. Passwords are entered there, never in this terminal.",
    )
    _add_provider_option(signup_cmd, default="email")
    _add_interaction_options(signup_cmd)
    signup_cmd.set_defaults(handler=_dispatch_auth_signup)

    login_cmd = subcommands.add_parser(
        "login",
        parents=[common],
        help="sign in in the browser",
        description="Sign in through Auth0's hosted login page.",
    )
    _add_provider_option(login_cmd, default=None)
    _add_interaction_options(login_cmd)
    login_cmd.set_defaults(handler=_dispatch_auth_login)

    status_cmd = subcommands.add_parser(
        "status",
        parents=[common],
        help="show the stored session",
        description="Show the stored session without contacting any server, unless --verify is given.",
    )
    status_cmd.add_argument(
        "--verify", action="store_true", help="refresh if needed and confirm the identity with the API"
    )
    status_cmd.set_defaults(handler=_dispatch_auth_status)

    logout_cmd = subcommands.add_parser(
        "logout",
        parents=[common],
        help="revoke and erase the stored session",
        description="Revoke the refresh token with Auth0 and erase the local session.",
    )
    logout_cmd.add_argument(
        "--local-only", action="store_true", help="erase the local session without contacting Auth0"
    )
    logout_cmd.set_defaults(handler=_dispatch_auth_logout)


def _add_api_commands(commands_sub: Subcommands, common: argparse.ArgumentParser) -> None:
    simulators = commands_sub.add_parser("simulators", parents=[common], help="simulator catalog")
    simulator_commands = simulators.add_subparsers(title="commands", metavar="COMMAND", required=True)
    list_sims = simulator_commands.add_parser("list", parents=[common], help="list the available simulators")
    _add_ephemeral_auth_options(list_sims)
    list_sims.set_defaults(handler=_dispatch_simulators_list)

    simulations = commands_sub.add_parser("simulations", parents=[common], help="submit simulations and check on them")
    simulation_commands = simulations.add_subparsers(title="commands", metavar="COMMAND", required=True)

    status_cmd = simulation_commands.add_parser("status", parents=[common], help="show a simulation's status")
    status_cmd.add_argument("simulation_id", metavar="ID", type=_positive_int, help="the simulation's numeric ID")
    _add_ephemeral_auth_options(status_cmd)
    status_cmd.set_defaults(handler=_dispatch_simulations_status)

    submit_cmd = simulation_commands.add_parser(
        "submit",
        parents=[common],
        help="submit an OMEX archive",
        description="Submit an existing OMEX archive. Prints the server's reference to the run; it does not wait.",
    )
    submit_cmd.add_argument("file", metavar="FILE", help="the .omex archive to upload")
    submit_cmd.add_argument(
        "--interval-time", metavar="N", type=_positive_float, help="output interval passed to the simulation"
    )
    submit_cmd.add_argument("--batch", action="store_true", help="submit as a batch job")
    _add_ephemeral_auth_options(submit_cmd)
    submit_cmd.set_defaults(handler=_dispatch_simulations_submit)


def _add_provider_option(parser: argparse.ArgumentParser, *, default: str | None) -> None:
    parser.add_argument(
        "--provider",
        choices=("email", "google"),
        default=default,
        help="identity provider to start with; with --device the choice is made on the hosted page instead",
    )


def _add_interaction_options(parser: argparse.ArgumentParser) -> None:
    how = parser.add_mutually_exclusive_group()
    how.add_argument("--device", action="store_true", help="sign in on another device (for SSH and headless use)")
    how.add_argument(
        "--no-browser", action="store_true", help="print the sign-in URL to open on this machine instead of opening it"
    )


def _add_ephemeral_auth_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ephemeral-auth",
        action="store_true",
        help="sign in for this command only, keeping credentials in memory (for hosts without a credential store)",
    )
    _add_interaction_options(parser)


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number")
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number")
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be a positive, finite number")
    return value


def _dispatch_show_config(args: argparse.Namespace) -> int:
    from compose_api_client import profiles

    loaded = profiles.load_cli_settings(args.profile)
    view = loaded.public_view()
    if args.json:
        print(json.dumps(view, indent=2))
    else:
        profile, config_file = view["profile"], view["config_file"]
        rows = [
            ("profile", profile["value"], profile["source"]),
            ("config file", config_file["path"], "found" if config_file["found"] else "not found"),
            *((name, entry["value"], entry["source"]) for name, entry in view["settings"].items()),
            *((name, value, "derived") for name, value in view["derived"].items()),
        ]
        width = max(len(name) for name, _, _ in rows)
        for name, value, source in rows:
            print(f"{name:<{width}}  {'-' if value is None else value}  ({source})")
    if loaded.settings.auth0_client_id is None:
        print(
            f"{PROG}: note: auth0_client_id is not set, so profile {loaded.settings.profile!r} cannot sign in yet",
            file=sys.stderr,
        )
    return int(ExitCode.OK)


def _dispatch_auth_signup(args: argparse.Namespace) -> int:
    from compose_api_client.cli.auth_commands import signup

    return signup(args)


def _dispatch_auth_login(args: argparse.Namespace) -> int:
    from compose_api_client.cli.auth_commands import login

    return login(args)


def _dispatch_auth_status(args: argparse.Namespace) -> int:
    from compose_api_client.cli.auth_commands import status

    return status(args)


def _dispatch_auth_logout(args: argparse.Namespace) -> int:
    from compose_api_client.cli.auth_commands import logout

    return logout(args)


def _dispatch_simulators_list(args: argparse.Namespace) -> int:
    from compose_api_client.cli.auth_commands import list_simulators

    return list_simulators(args)


def _dispatch_simulations_status(args: argparse.Namespace) -> int:
    from compose_api_client.cli.auth_commands import simulation_status

    return simulation_status(args)


def _dispatch_simulations_submit(args: argparse.Namespace) -> int:
    from compose_api_client.cli.auth_commands import submit_simulation

    return submit_simulation(args)


def _report_argparse(args: argparse.Namespace, category: str, message: str, code: ExitCode) -> int:
    print(f"{PROG}: error: {printable_lines(message)}", file=sys.stderr)
    if getattr(args, "json", False):
        print(json.dumps({"error": {"category": category, "message": message, "exit_code": int(code)}}))
    return int(code)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if getattr(args, "ephemeral_auth", True) is False and (args.device or args.no_browser):
            parser.error(
                "--device and --no-browser choose how --ephemeral-auth signs in, so they need --ephemeral-auth"
            )
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else int(ExitCode.USAGE)
    args.profile = getattr(args, "profile", None)
    args.json = getattr(args, "json", False)

    handler: Handler = args.handler
    try:
        return handler(args)
    except CliError as exc:
        return _report_argparse(args, exc.category, exc.message, exc.exit_code)
    except KeyboardInterrupt:
        print(f"{PROG}: cancelled", file=sys.stderr)
        return int(ExitCode.CANCELLED)
    except Exception as exc:
        return _report_argparse(
            args, "internal", f"internal error ({type(exc).__name__}); this is a bug in {PROG}", ExitCode.FAILURE
        )


# -- SED-ML runs and comparisons ----------------------------------------------------------------------------------

Archive = Annotated[
    Path, typer.Argument(help="A COMBINE/OMEX archive with SED-ML and its models.", exists=True, dir_okay=False)
]
SolverOption = Annotated[
    list[str] | None, typer.Option("--solver", "-s", help="A solver id (repeatable); all when omitted.")
]


def _listed(value: object) -> list[str]:
    """A generated model's optional list field (`UNSET` when absent) as a list."""
    return [str(v) for v in value] if isinstance(value, list) else []


@sedml_app.command("preview")
@claims("sedml preview", "preview-sedml")
@handled
def sedml_preview(ctx: typer.Context, archive: Archive, solver: SolverOption = None) -> None:
    """Translate an archive without running it: its tasks, the solvers that accept each, and the findings."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        preview = s.sedml_preview(archive, solvers=solver or ())
    if settings.output is Output.JSON:
        emit(Output.JSON, preview.to_dict())
        return
    rows = [
        {
            "task": t.task,
            "sedml": t.sedml,
            "solvers": ", ".join(t.solvers),
            "refused": ", ".join(_listed(t.refused)) or None,
            "reports": ", ".join(_listed(t.reports)),
        }
        for t in preview.tasks
    ]
    emit(settings.output, rows, ["task", "sedml", "solvers", "refused", "reports"])
    for f in preview.findings:
        err.print(f"{f.severity} {f.code} {f.solver or ''} {f.task or ''}: {f.message}")


@sedml_app.command("run")
@claims("sedml run", "run-sedml")
@handled
def sedml_run(
    ctx: typer.Context,
    archive: Archive,
    solver: SolverOption = None,
    task: Annotated[list[str] | None, typer.Option(help="A SED-ML task id (repeatable); all when omitted.")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="A tag for every run (repeatable).")] = None,
    description: Annotated[str | None, typer.Option(help="What the runs are for.")] = None,
) -> None:
    """Run each task once per solver; prints each task's comparison and its runs."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        result = s.sedml_run(archive, solvers=solver or (), tasks=task or (), tags=tag or (), description=description)
    if settings.output is Output.JSON:
        emit(Output.JSON, result.to_dict())
        return
    rows = [
        {"comparison": c.comparison_id, "task": c.task, "solver": m.solver, "simulation": m.simulation_id}
        for c in result.comparisons
        for m in c.members
    ]
    emit(settings.output, rows, ["comparison", "task", "solver", "simulation"])


@comparisons_app.command("list")
@claims("comparisons list", "list-comparisons")
@handled
def comparisons_list(
    ctx: typer.Context,
    source: Annotated[str | None, typer.Option(help="Only this source, e.g. upload:x.omex.")] = None,
    limit: Annotated[int, typer.Option(help="At most this many.")] = 25,
    offset: Annotated[int, typer.Option(help="Skip this many.")] = 0,
) -> None:
    """Comparisons, newest first."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        page = s.comparisons(source=source, limit=limit, offset=offset)
    rows = [
        {
            "comparison": c.comparison_id,
            "name": c.name,
            "status": str(c.status),
            "close": c.close,
            "solvers": ", ".join(m.solver for m in c.members),
        }
        for c in page.comparisons
    ]
    emit(settings.output, rows if settings.output is not Output.JSON else [c.to_dict() for c in page.comparisons],
         ["comparison", "name", "status", "close", "solvers"])  # fmt: skip


@comparisons_app.command("show")
@claims("comparisons show", "get-comparison")
@handled
def comparisons_show(
    ctx: typer.Context, comparison_id: Annotated[int, typer.Argument(help="The comparison id.")]
) -> None:
    """One comparison: its runs, and per report the worst data set once every run has finished."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        emit(settings.output, s.comparison(comparison_id).to_dict())


# -- sources -------------------------------------------------------------------------------------------------------

Out = Annotated[Path | None, typer.Option("--out", "-O", help="Write the archive here (a file or a directory).")]


def _save_archive(content: bytes, name: str, out: Path | None) -> Path:
    target = out if out is not None else Path.cwd()
    path = target / name if target.is_dir() else target
    path.write_bytes(content)
    return path


def _run_rows(result: Any) -> list[dict[str, Any]]:
    return [
        {"comparison": c.comparison_id, "task": c.task, "solver": m.solver, "simulation": m.simulation_id}
        for c in result.comparisons
        for m in c.members
    ]


@biomodels_app.command("search")
@claims("biomodels search", "search-biomodels")
@handled
def biomodels_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Words to search for.")],
    limit: Annotated[int, typer.Option(help="At most this many.")] = 20,
    all_models: Annotated[bool, typer.Option("--all", help="Not only manually curated models.")] = False,
) -> None:
    """Search EBI BioModels (manually curated models unless --all)."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        hits = s.biomodels_search(query, limit=limit, curated=not all_models)
    emit(settings.output, [h.to_dict() for h in hits], ["id", "name", "format"])


@biomodels_app.command("show")
@claims("biomodels show", "get-biomodel")
@handled
def biomodels_show(ctx: typer.Context, model_id: Annotated[str, typer.Argument(help="e.g. BIOMD0000000012")]) -> None:
    """One BioModels entry: name, curation status, latest revision."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        emit(settings.output, s.biomodel(model_id).to_dict())


@biomodels_app.command("get")
@claims("biomodels get", "get-biomodel-omex")
@handled
def biomodels_get(
    ctx: typer.Context, model_id: Annotated[str, typer.Argument(help="e.g. BIOMD0000000012")], out: Out = None
) -> None:
    """Download the entry's COMBINE archive."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        path = _save_archive(s.biomodel_omex(model_id), f"{model_id}.omex", out)
    emit(settings.output, {"model": model_id, "file": str(path)})


@biomodels_app.command("run")
@claims("biomodels run", "run-biomodel")
@handled
def biomodels_run(
    ctx: typer.Context,
    model_id: Annotated[str, typer.Argument(help="e.g. BIOMD0000000012")],
    solver: SolverOption = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="A tag for every run (repeatable).")] = None,
) -> None:
    """Run the entry's SED-ML once per solver; prints each task's comparison and its runs."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        result = s.run_biomodel(model_id, solvers=solver or (), tags=tag or ())
    emit(settings.output, _run_rows(result) if settings.output is not Output.JSON else result.to_dict(),
         ["comparison", "task", "solver", "simulation"])  # fmt: skip


@biosimulations_app.command("search")
@claims("biosimulations search", "search-biosimulations-projects")
@handled
def biosimulations_search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Part of a project id.")] = "",
    limit: Annotated[int, typer.Option(help="At most this many.")] = 20,
) -> None:
    """biosimulations.org projects whose id contains the query."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        found = s.biosimulations_search(query, limit=limit)
    emit(settings.output, [p.to_dict() for p in found], ["id", "run", "updated"])


@biosimulations_app.command("show")
@claims("biosimulations show", "get-biosimulations-project")
@handled
def biosimulations_show(ctx: typer.Context, project_id: Annotated[str, typer.Argument(help="The project id.")]) -> None:
    """One project: its run and the simulator that ran it."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        emit(settings.output, s.biosimulations_project(project_id).to_dict())


@biosimulations_app.command("get")
@claims("biosimulations get", "get-biosimulations-omex")
@handled
def biosimulations_get(
    ctx: typer.Context, project_id: Annotated[str, typer.Argument(help="The project id.")], out: Out = None
) -> None:
    """Download the project's archive."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        path = _save_archive(s.biosimulations_omex(project_id), f"{project_id}.omex", out)
    emit(settings.output, {"project": project_id, "file": str(path)})


@biosimulations_app.command("reference")
@claims("biosimulations reference", "get-biosimulations-reference")
@handled
def biosimulations_reference(
    ctx: typer.Context, project_id: Annotated[str, typer.Argument(help="The project id.")]
) -> None:
    """The project's original results: each report's labels and number of points (--output json for the values)."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        reference = s.biosimulations_reference(project_id)
    if settings.output is Output.JSON:
        emit(Output.JSON, reference)
        return
    rows = [{"report": k, "labels": len(v), "points": len(next(iter(v.values()), []))} for k, v in reference.items()]
    emit(settings.output, rows, ["report", "labels", "points"])


@biosimulations_app.command("run")
@claims("biosimulations run", "run-biosimulations-project")
@handled
def biosimulations_run(
    ctx: typer.Context,
    project_id: Annotated[str, typer.Argument(help="The project id.")],
    solver: SolverOption = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", "-t", help="A tag for every run (repeatable).")] = None,
) -> None:
    """Run the project's SED-ML once per solver, its original results as the reference."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        result = s.run_biosimulations_project(project_id, solvers=solver or (), tags=tag or ())
    emit(settings.output, _run_rows(result) if settings.output is not Output.JSON else result.to_dict(),
         ["comparison", "task", "solver", "simulation"])  # fmt: skip


@comparisons_app.command("series")
@claims("comparisons series", "get-comparison-series")
@handled
def comparisons_series(
    ctx: typer.Context,
    comparison_id: Annotated[int, typer.Argument(help="The comparison id.")],
    report: Annotated[str, typer.Option(help="The SED-ML report id.")],
) -> None:
    """One report's columns from each run and each reference (JSON; a table lists what is there)."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        series = s.comparison_series(comparison_id, report)
    if settings.output is Output.JSON:
        emit(Output.JSON, series.to_dict())
        return
    data = series.to_dict()
    rows = [
        {"from": name, "kind": kind, "labels": len(columns)}
        for kind in ("solvers", "references")
        for name, columns in data[kind].items()
    ]
    emit(settings.output, rows, ["from", "kind", "labels"])


# -- suites --------------------------------------------------------------------------------------------------------

SuiteName = Annotated[str, typer.Argument(help="The suite, e.g. biomodels-ode-sample.")]


@suites_app.command("list")
@claims("suites list", "list-suites")
@handled
def suites_list(ctx: typer.Context) -> None:
    """The suites: their sources, solvers and accepted baseline run."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        found = s.suites()
    rows = [
        {
            "name": x.name,
            "sources": len(x.sources),
            "solvers": ", ".join(_listed(x.solvers)) or "all",
            "baseline": x.baseline if isinstance(x.baseline, int) else None,
        }
        for x in found
    ]
    emit(settings.output, rows if settings.output is not Output.JSON else [x.to_dict() for x in found],
         ["name", "sources", "solvers", "baseline"])  # fmt: skip


@suites_app.command("runs")
@claims("suites runs", "list-suite-runs")
@handled
def suites_runs(ctx: typer.Context, name: SuiteName) -> None:
    """A suite's runs, newest first."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        emit(settings.output, [r.to_dict() for r in s.suite_runs(name)], ["number", "created_at", "status"])


@suites_app.command("show")
@claims("suites show", "get-suite-run")
@handled
def suites_show(
    ctx: typer.Context, name: SuiteName, number: Annotated[int, typer.Argument(help="The run's number.")]
) -> None:
    """One suite run: per source, whether the solvers agree, match references, and drifted from the baseline."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        view = s.suite_run(name, number)
    if settings.output is Output.JSON:
        emit(Output.JSON, view.to_dict())
        return
    rows = [
        {
            "source": r.get("source"),
            "task": r.get("task"),
            "status": r.get("status"),
            "agree": r.get("close"),
            "references": r.get("close_to_references"),
            "worst": r.get("worst_label"),
            "drift": ", ".join(f"{k}:{'ok' if v.get('close') else 'DRIFT'}" for k, v in (r.get("drift") or {}).items())
            or None,
            "note": r.get("expected") or r.get("failure"),
        }
        for r in view.to_dict()["rows"]
    ]
    emit(settings.output, rows, ["source", "task", "status", "agree", "references", "worst", "drift", "note"])


@suites_app.command("run")
@claims("suites run", "run-suite")
@handled
def suites_run(ctx: typer.Context, name: SuiteName) -> None:
    """Run every source of the suite on its solvers; prints the new run's number."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        emit(settings.output, s.run_suite(name).to_dict())


@app.command("build-log")
@claims("build-log", "get-simulator-build-log")
@handled
def build_log(
    ctx: typer.Context, simulator_id: Annotated[int, typer.Argument(help="The simulator id (a run's simulator_id).")]
) -> None:
    """The SLURM log of a simulator's newest container build."""
    settings = _settings(ctx)
    with make_session(settings) as s:
        text = s.build_log(simulator_id)
    if settings.output is Output.JSON:
        emit(Output.JSON, {"simulator_id": simulator_id, "log": text})
    else:
        print(text, end="")
