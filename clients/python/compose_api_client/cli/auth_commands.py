"""`auth signup`, `auth login`, `auth status`, `auth logout`, `config show`, and authenticated CLI operations."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import zipfile
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from compose_api_client import profiles
from compose_api_client.auth.identity import ComposeApi, OneCommandSession, StoredSession, confirm_identity
from compose_api_client.auth.models import Provider, SignInRequest
from compose_api_client.auth.oauth import Auth0OAuthClient
from compose_api_client.auth.session import AuthSession, AuthStatus, LogoutResult
from compose_api_client.auth.signin import connection_for, ephemeral_session, persistent_sign_in
from compose_api_client.cli.render import emit_json, emit_text, notify, printable
from compose_api_client.cli.wiring import Wiring, run
from compose_api_client.ext.credentials import TOKEN_ENV_VAR, EnvironmentToken
from compose_api_client.ext.errors import ExitCode, UsageError
from compose_api_client.models import HpcRun, RegisteredSimulators, SimulationExperiment
from compose_api_client.profiles import CliSettings
from compose_api_client.types import Unset

T = TypeVar("T")


def signup(args: argparse.Namespace, wiring: Wiring | None = None) -> int:
    return sign_in_command(args, signup=True, wiring=wiring)


def login(args: argparse.Namespace, wiring: Wiring | None = None) -> int:
    return sign_in_command(args, signup=False, wiring=wiring)


def sign_in_command(args: argparse.Namespace, *, signup: bool, wiring: Wiring | None = None) -> int:
    """Sign in, keep the session, then have the API confirm who it is. Success means all three happened."""
    settings = profiles.load_cli_settings(args.profile).settings
    wiring = wiring or Wiring()
    request = SignInRequest(
        signup=signup,
        provider=None if args.provider is None else Provider(args.provider),
        device=args.device,
        open_browser=not args.no_browser,
        persistent=True,
    )
    settings.require_client_id()
    connection_for(settings, request)
    store = wiring.store(settings, writable=True)

    async def sign_in_and_confirm() -> AuthStatus:
        await persistent_sign_in(
            settings, request, store, notify=notify, launcher=wiring.browser(), transport=wiring.auth0_transport
        )
        notify(f"Signed in. Confirming the session with the Compose API at {settings.api_base_url}...")
        return await confirm_identity(
            settings,
            store,
            auth0_transport=wiring.auth0_transport,
            api_transport=wiring.api_transport,
            after_sign_in=True,
        )

    status_result = run(sign_in_and_confirm())
    _show_status(settings, status_result, args.json, checked_with_api=True)
    return int(ExitCode.OK)


def status(args: argparse.Namespace, wiring: Wiring | None = None) -> int:
    """Without --verify, only the local record is read: no network, no renewal, and no claim about the API."""
    settings = profiles.load_cli_settings(args.profile).settings
    if TOKEN_ENV_VAR in os.environ:
        env_token = EnvironmentToken()
        return _env_token_status(settings, env_token, args, wiring or Wiring())
    settings.require_client_id()
    wiring = wiring or Wiring()
    store = wiring.store(settings, writable=False)
    session = AuthSession(settings, store)
    local = run(session.status())
    if args.verify and local.state != "missing":
        local = run(
            confirm_identity(
                settings,
                store,
                auth0_transport=wiring.auth0_transport,
                api_transport=wiring.api_transport,
                after_sign_in=False,
            )
        )
        _show_status(settings, local, args.json, checked_with_api=True)
        return int(ExitCode.OK)
    _show_status(settings, local, args.json, checked_with_api=False)
    return int(ExitCode.AUTH_REQUIRED) if local.state in {"missing", "expired"} else int(ExitCode.OK)


def _env_token_status(
    settings: CliSettings, env_token: EnvironmentToken, args: argparse.Namespace, wiring: Wiring
) -> int:
    from compose_api_client.auth.models import Identity
    from compose_api_client.ext.session import AsyncComposeSession

    identity: Identity | None = None
    if args.verify:

        async def check_env() -> Identity:
            async with AsyncComposeSession(
                settings.api_base_url,
                tokens=env_token.as_async(),
                ca_bundle=settings.ca_bundle,
                transport=wiring.api_transport,
            ) as api_session:
                principal = await api_session.whoami()
                return Identity(issuer=principal.issuer, subject=principal.subject)

        identity = run(check_env())

    if args.json:
        emit_json({
            "profile": settings.profile,
            "api_base_url": settings.api_base_url,
            "state": "valid",
            "source": f"environment ({TOKEN_ENV_VAR})",
            "identity": None if identity is None else identity.model_dump(mode="json"),
            "expires_at": None,
            "renewable": False,
            "api_verified_at": None,
            "checked_with_api": bool(args.verify),
        })
        return int(ExitCode.OK)
    emit_text(f"Profile {settings.profile} ({settings.api_base_url})")
    emit_text(f"Source: environment ({TOKEN_ENV_VAR}); not renewable")
    if identity is not None:
        emit_text(f"Identity: {printable(identity.subject)} ({printable(identity.issuer)})")
        emit_text("API: confirmed this identity just now")
    else:
        emit_text("API: not checked (run `compose-api auth status --verify` to check now)")
    return int(ExitCode.OK)


def logout(args: argparse.Namespace, wiring: Wiring | None = None) -> int:
    settings = profiles.load_cli_settings(args.profile).settings
    settings.require_client_id()
    wiring = wiring or Wiring()
    # Do not parse an existing record before logout: corrupt records must remain removable.
    session = AuthSession(settings, wiring.store(settings, writable=False, check=False))

    async def end() -> LogoutResult:
        if args.local_only:
            return await session.logout()
        async with Auth0OAuthClient(settings, transport=wiring.auth0_transport) as client:
            return await session.logout(client)

    result = run(end())
    if args.json:
        emit_json(result.model_dump(mode="json"))
    else:
        emit_text(f"Local credentials cleared; remote revocation: {result.revocation}.")
    notify(
        "This erased the session on this computer only. Already issued access tokens may work until they expire, and"
        " Auth0 and Google browser sessions stay signed in."
    )
    return int(ExitCode.NETWORK) if result.revocation == "unavailable" else int(ExitCode.OK)


def show_config(args: argparse.Namespace) -> int:
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
            f"compose-api: note: auth0_client_id is not set, so profile {loaded.settings.profile!r} cannot sign in yet",
            file=sys.stderr,
        )
    return int(ExitCode.OK)


def _show_status(settings: CliSettings, status_obj: AuthStatus, as_json: bool, *, checked_with_api: bool) -> None:
    if as_json:
        document: dict[str, Any] = status_obj.model_dump(mode="json")
        document["checked_with_api"] = checked_with_api
        emit_json(document)
        return
    emit_text(f"Profile {settings.profile} ({settings.api_base_url})")
    if status_obj.identity is None or status_obj.expires_at is None:
        emit_text("No session. Sign in with: compose-api auth login")
        return
    renewal = "renewable" if status_obj.renewable else "not renewable: sign in again when it expires"
    state_str = status_obj.state.replace("_", " ")
    emit_text(f"Identity: {printable(status_obj.identity.subject)} ({printable(status_obj.identity.issuer)})")
    emit_text(f"Session: {state_str}, until {status_obj.expires_at:%Y-%m-%d %H:%M} UTC; {renewal}")
    if checked_with_api:
        emit_text("API: confirmed this identity just now")
    elif status_obj.api_verified_at is not None:
        emit_text(
            f"API: last confirmed {status_obj.api_verified_at:%Y-%m-%d %H:%M} UTC (stored record only; run"
            " `compose-api auth status --verify` to check now)"
        )
    else:
        emit_text("API: never confirmed (run `compose-api auth status --verify`)")


# -- Authenticated API commands (`simulators list`, `simulations status`, `simulations submit`) --


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
    path = _omex_archive(args.file)
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
    settings = profiles.load_cli_settings(args.profile).settings
    settings.require_client_id()
    return settings


def _call(
    args: argparse.Namespace,
    wiring: Wiring | None,
    operation: Callable[[ComposeApi], Awaitable[T]],
    *,
    settings: CliSettings | None = None,
) -> T:
    settings = settings or _settings(args)
    wiring = wiring or Wiring()
    if getattr(args, "ephemeral_auth", False):
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
        emit_text("No simulators are registered on this server.")
        return
    rows = [("ID", "DEFINITION", "PACKAGES", "REGISTERED")]
    for version in simulators.versions:
        packages = version.packages if isinstance(version.packages, list) else []
        rows.append((
            str(version.database_id),
            printable(version.container_def_hash)[:12],
            str(len(packages)),
            _when(version.created_at),
        ))
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    for row in rows:
        emit_text("  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip())


def _show_run(simulation_id: int, record: HpcRun) -> None:
    status_val = record.status if record.status is not None and not isinstance(record.status, Unset) else "unknown"
    emit_text(f"Simulation {simulation_id}: {status_val}")
    emit_text(f"  {record.job_type} job, SLURM ID {record.slurmjobid}")
    emit_text(f"  started {_when(record.start_time)}, ended {_when(record.end_time)}")
    if isinstance(record.error_message, str) and record.error_message:
        emit_text(f"  error: {printable(record.error_message)}")


def _show_submission(experiment: SimulationExperiment) -> None:
    simulation_id = experiment.simulation_database_id
    emit_text(f"Submitted simulation {simulation_id} (simulator {experiment.simulator_database_id}).")
    emit_text(f"It runs on the server; check on it with: compose-api simulations status {simulation_id}")
