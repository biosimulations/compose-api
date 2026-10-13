"""`auth signup`, `auth login`, `auth status` and `auth logout`."""

import argparse
from typing import Any

from compose_api.cli.api import ComposeApi, StoredSession
from compose_api.cli.auth.models import Provider, SignInRequest
from compose_api.cli.auth.oauth import Auth0OAuthClient
from compose_api.cli.auth.session import AuthSession, AuthStatus, LogoutResult
from compose_api.cli.auth.signin import connection_for, persistent_sign_in
from compose_api.cli.auth.storage import CredentialStore
from compose_api.cli.commands.common import Wiring, run
from compose_api.cli.config import CliSettings, load_cli_settings
from compose_api.cli.errors import CliError, ExitCode, NetworkError
from compose_api.cli.output import emit, emit_json, notify, printable


def signup(args: argparse.Namespace, wiring: Wiring | None = None) -> int:
    return sign_in_command(args, signup=True, wiring=wiring)


def login(args: argparse.Namespace, wiring: Wiring | None = None) -> int:
    return sign_in_command(args, signup=False, wiring=wiring)


def sign_in_command(args: argparse.Namespace, *, signup: bool, wiring: Wiring | None = None) -> int:
    """Sign in, keep the session, then have the API confirm who it is. Success means all three happened."""
    settings = load_cli_settings(args.profile).settings
    wiring = wiring or Wiring()
    request = SignInRequest(
        signup=signup,
        provider=None if args.provider is None else Provider(args.provider),
        device=args.device,
        open_browser=not args.no_browser,
        persistent=True,
    )
    # Everything that can be wrong locally is found before any network request or browser window: the profile, the
    # provider's connection, and somewhere to keep the session.
    settings.require_client_id()
    connection_for(settings, request)
    store = wiring.store(settings, writable=True)

    async def sign_in_and_confirm() -> AuthStatus:
        await persistent_sign_in(
            settings, request, store, notify=notify, launcher=wiring.browser(), transport=wiring.auth0_transport
        )
        notify(f"Signed in. Confirming the session with the Compose API at {settings.api_base_url}...")
        return await _confirm(settings, store, wiring, after_sign_in=True)

    status = run(sign_in_and_confirm())
    _show_status(settings, status, args.json, checked_with_api=True)
    return int(ExitCode.OK)


def status(args: argparse.Namespace, wiring: Wiring | None = None) -> int:
    """Without --verify, only the local record is read: no network, no renewal, and no claim about the API."""
    settings = load_cli_settings(args.profile).settings
    settings.require_client_id()
    wiring = wiring or Wiring()
    store = wiring.store(settings, writable=False)
    session = AuthSession(settings, store)
    local = run(session.status())
    if args.verify and local.state != "missing":
        local = run(_confirm(settings, store, wiring, after_sign_in=False))
        _show_status(settings, local, args.json, checked_with_api=True)
        return int(ExitCode.OK)
    _show_status(settings, local, args.json, checked_with_api=False)
    return int(ExitCode.AUTH_REQUIRED) if local.state in {"missing", "expired"} else int(ExitCode.OK)


def logout(args: argparse.Namespace, wiring: Wiring | None = None) -> int:
    settings = load_cli_settings(args.profile).settings
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
        emit(f"Local credentials cleared; remote revocation: {result.revocation}.")
    notify(
        "This erased the session on this computer only. Already issued access tokens may work until they expire, and"
        " Auth0 and Google browser sessions stay signed in."
    )
    return int(ExitCode.NETWORK) if result.revocation == "unavailable" else int(ExitCode.OK)


async def _confirm(settings: CliSettings, store: CredentialStore, wiring: Wiring, *, after_sign_in: bool) -> AuthStatus:
    """Renew if needed, ask the API who this session is, and record the confirmation."""
    session = AuthSession(settings, store)
    try:
        async with Auth0OAuthClient(settings, transport=wiring.auth0_transport) as oauth:
            await ComposeApi(settings, StoredSession(session, oauth), transport=wiring.api_transport).verify_identity()
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


def _show_status(settings: CliSettings, status: AuthStatus, as_json: bool, *, checked_with_api: bool) -> None:
    if as_json:
        document: dict[str, Any] = status.model_dump(mode="json")
        document["checked_with_api"] = checked_with_api
        emit_json(document)
        return
    emit(f"Profile {settings.profile} ({settings.api_base_url})")
    if status.identity is None or status.expires_at is None:
        emit("No session. Sign in with: compose-api auth login")
        return
    renewal = "renewable" if status.renewable else "not renewable: sign in again when it expires"
    emit(f"Identity: {printable(status.identity.subject)} ({printable(status.identity.issuer)})")
    emit(f"Session: {status.state.replace('_', ' ')}, until {status.expires_at:%Y-%m-%d %H:%M} UTC; {renewal}")
    if checked_with_api:
        emit("API: confirmed this identity just now")
    elif status.api_verified_at is not None:
        emit(
            f"API: last confirmed {status.api_verified_at:%Y-%m-%d %H:%M} UTC (stored record only; run"
            " `compose-api auth status --verify` to check now)"
        )
    else:
        emit("API: never confirmed (run `compose-api auth status --verify`)")
