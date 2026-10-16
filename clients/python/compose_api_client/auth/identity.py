"""Confirm a saved identity through the shared session HTTP boundary."""

from __future__ import annotations

import httpx

from compose_api_client.auth.oauth import Auth0OAuthClient
from compose_api_client.auth.session import AuthSession, AuthStatus
from compose_api_client.auth.sources import AsyncStoredSession
from compose_api_client.auth.storage import CredentialStore
from compose_api_client.ext.errors import CliError, NetworkError
from compose_api_client.ext.session import AsyncComposeSession
from compose_api_client.profiles import CliSettings


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
        async with (
            Auth0OAuthClient(settings, transport=auth0_transport) as oauth,
            AsyncComposeSession(
                settings.api_base_url,
                tokens=AsyncStoredSession(session, oauth),
                ca_bundle=settings.ca_bundle,
                transport=api_transport,
            ) as api,
        ):
            await api.whoami()
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
