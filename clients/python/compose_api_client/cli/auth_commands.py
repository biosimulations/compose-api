"""`auth signup`, `auth login`, `auth status` and `auth logout`; `config show` and API commands are in `commands`."""

from __future__ import annotations

import argparse
import os
from typing import Any

from compose_api_client import profiles
from compose_api_client.auth.identity import confirm_identity
from compose_api_client.auth.models import Provider, SignInMethod, SignInRequest
from compose_api_client.auth.oauth import Auth0OAuthClient
from compose_api_client.auth.session import AuthSession, AuthStatus, LogoutResult
from compose_api_client.auth.signin import connection_for, persistent_sign_in
from compose_api_client.cli.render import emit_json, emit_text, notify, printable
from compose_api_client.cli.wiring import Wiring as Wiring  # re-exported: tests replace it here
from compose_api_client.cli.wiring import run
from compose_api_client.ext.credentials import TOKEN_ENV_VAR, EnvironmentToken
from compose_api_client.ext.errors import ExitCode
from compose_api_client.profiles import CliSettings


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
        method=SignInMethod(args.method),
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
            "state": "valid" if args.verify else "unverified",
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
    emit_text(f"State: {'valid' if args.verify else 'unverified'}")
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
