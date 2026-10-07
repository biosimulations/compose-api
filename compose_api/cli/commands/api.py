"""`simulators list`, `simulations status` and `simulations submit`.

Each needs a session. Without `--ephemeral-auth` that is the stored one, and its absence is an error, never an
anonymous request and never a sign-in the person did not ask for. With `--ephemeral-auth` the command signs in for
itself, keeps the credentials in memory and drops them when it ends.
"""

import argparse
import stat
import zipfile
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from compose_api.api.client.models import HpcRun, RegisteredSimulators, SimulationExperiment
from compose_api.api.client.types import Unset
from compose_api.cli.api import ComposeApi, OneCommandSession, StoredSession
from compose_api.cli.auth.models import SignInRequest
from compose_api.cli.auth.oauth import Auth0OAuthClient
from compose_api.cli.auth.session import AuthSession
from compose_api.cli.auth.signin import ephemeral_session
from compose_api.cli.commands.common import Wiring, run
from compose_api.cli.config import CliSettings, load_cli_settings
from compose_api.cli.errors import ExitCode, UsageError
from compose_api.cli.output import emit, emit_json, notify, printable


def list_simulators(args: argparse.Namespace, wiring: Wiring | None = None) -> int:
    simulators = _call(args, wiring, lambda api: api.list_simulators())
    if args.json:
        emit_json(simulators.to_dict())
    else:
        _show_simulators(simulators)
    return int(ExitCode.OK)


def simulation_status(args: argparse.Namespace, wiring: Wiring | None = None) -> int:
    run_record = _call(args, wiring, lambda api: api.simulation_status(args.simulation_id))
    if args.json:
        emit_json(run_record.to_dict())
    else:
        _show_run(args.simulation_id, run_record)
    return int(ExitCode.OK)


def submit_simulation(args: argparse.Namespace, wiring: Wiring | None = None) -> int:
    settings = _settings(args)
    path = _omex_archive(args.file)  # checked before any sign-in or upload
    with path.open("rb") as archive:
        experiment = _call(
            args,
            wiring,
            lambda api: api.submit_simulation(
                archive, file_name=path.name, interval_time=args.interval_time, batch=args.batch
            ),
            settings=settings,
        )
    if args.json:
        emit_json(experiment.to_dict())
    else:
        _show_submission(experiment)
    return int(ExitCode.OK)


def _settings(args: argparse.Namespace) -> CliSettings:
    settings = load_cli_settings(args.profile).settings
    settings.require_client_id()
    return settings


def _call[T](
    args: argparse.Namespace,
    wiring: Wiring | None,
    operation: Callable[[ComposeApi], Awaitable[T]],
    *,
    settings: CliSettings | None = None,
) -> T:
    settings = settings or _settings(args)
    wiring = wiring or Wiring()
    if args.ephemeral_auth:
        request = SignInRequest(
            signup=False, provider=None, device=args.device, open_browser=not args.no_browser, persistent=False
        )

        async def once() -> T:
            async with ephemeral_session(
                settings, request, notify=notify, launcher=wiring.browser(), transport=wiring.auth0_transport
            ) as record:
                return await operation(ComposeApi(settings, OneCommandSession(record), transport=wiring.api_transport))

        return run(once())

    store = wiring.store(settings, writable=False)

    async def stored() -> T:
        async with Auth0OAuthClient(settings, transport=wiring.auth0_transport) as oauth:
            tokens = StoredSession(AuthSession(settings, store), oauth)
            return await operation(ComposeApi(settings, tokens, transport=wiring.api_transport))

    return run(stored())


def _omex_archive(name: str) -> Path:
    path = Path(name).expanduser()
    shown = printable(name)
    try:
        info = path.stat()
    except OSError:
        raise UsageError(f"cannot read {shown}") from None
    if not stat.S_ISREG(info.st_mode):
        raise UsageError(f"{shown} is not a regular file")
    try:
        if info.st_size == 0 or not zipfile.is_zipfile(path):
            raise UsageError(f"{shown} is not an OMEX archive (a ZIP file); nothing was uploaded")
    except OSError:
        raise UsageError(f"cannot read {shown}") from None
    return path


def _when(value: Any) -> str:
    if isinstance(value, datetime):
        return f"{value:%Y-%m-%d %H:%M}"
    return "-" if value is None or isinstance(value, Unset) else printable(str(value))


def _show_simulators(simulators: RegisteredSimulators) -> None:
    if not simulators.versions:
        emit("No simulators are registered on this server.")
        return
    rows = [("ID", "DEFINITION", "PACKAGES", "REGISTERED")]
    for version in simulators.versions:
        packages = version.packages if isinstance(version.packages, list) else []
        rows.append((
            str(version.database_id),
            printable(version.container_def_hash)[:12],  # a short hash, as git shows one
            str(len(packages)),
            _when(version.created_at),
        ))
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    for row in rows:
        emit("  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip())


def _show_run(simulation_id: int, record: HpcRun) -> None:
    status = record.status if record.status is not None and not isinstance(record.status, Unset) else "unknown"
    emit(f"Simulation {simulation_id}: {status}")
    emit(f"  {record.job_type} job, SLURM ID {record.slurmjobid}")
    emit(f"  started {_when(record.start_time)}, ended {_when(record.end_time)}")
    if isinstance(record.error_message, str) and record.error_message:
        emit(f"  error: {printable(record.error_message)}")


def _show_submission(experiment: SimulationExperiment) -> None:
    simulation_id = experiment.simulation_database_id
    emit(f"Submitted simulation {simulation_id} (simulator {experiment.simulator_database_id}).")
    emit(f"It runs on the server; check on it with: compose-api simulations status {simulation_id}")
