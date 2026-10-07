"""Choosing a sign-in flow, and keeping its result only once it is fully validated."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx

from compose_api.cli.auth.browser import BrowserLauncher, browser_sign_in, open_system_browser
from compose_api.cli.auth.device import device_sign_in
from compose_api.cli.auth.models import Notify, Provider, SessionRecord, SignInRequest, TokenGrant
from compose_api.cli.auth.oauth import Auth0OAuthClient
from compose_api.cli.auth.session import AuthSession
from compose_api.cli.auth.storage import CredentialStore, MemoryCredentialStore
from compose_api.cli.config import CliSettings
from compose_api.cli.errors import ConfigError


def connection_for(settings: CliSettings, request: SignInRequest) -> str | None:
    """The Auth0 connection to steer the browser to. Raises before anything touches the network or a browser.

    The device endpoint takes no connection, so with --device the person picks the provider on the hosted page.
    """
    if request.device:
        return None
    if request.provider is Provider.GOOGLE:
        if settings.google_connection is None:
            raise ConfigError(
                f"--provider google needs google_connection set for profile {settings.profile!r}: the tenant's"
                " Google connection name, often google-oauth2. Or sign in with --device and choose Google there"
            )
        return settings.google_connection
    if request.provider is Provider.EMAIL:
        return settings.database_connection  # optional: without it the hosted page offers every enabled connection
    return None


async def sign_in(
    settings: CliSettings,
    request: SignInRequest,
    *,
    notify: Notify,
    launcher: BrowserLauncher = open_system_browser,
    transport: httpx.AsyncBaseTransport | None = None,
) -> TokenGrant:
    """Run the browser or device flow the request asks for. Never switches from one to the other on failure."""
    connection = connection_for(settings, request)
    async with Auth0OAuthClient(settings, transport=transport) as client:
        if request.device:
            return await device_sign_in(client, request, notify=notify)
        return await browser_sign_in(client, request, connection=connection, launcher=launcher, notify=notify)


async def persistent_sign_in(
    settings: CliSettings,
    request: SignInRequest,
    store: CredentialStore,
    *,
    notify: Notify,
    launcher: BrowserLauncher = open_system_browser,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SessionRecord:
    """Sign in and replace the stored session.

    Cancellation or flow failure preserves the previous session. Commit rechecks the generation under lock;
    an uncertain storage failure invalidates local credentials instead of leaving a partial replacement usable.
    """
    session = AuthSession(settings, store)
    async with session.login_transaction() as snapshot:
        grant = await sign_in(
            settings, replace(request, persistent=True), notify=notify, launcher=launcher, transport=transport
        )
        return await session.commit(grant, snapshot)


@asynccontextmanager
async def ephemeral_session(
    settings: CliSettings,
    request: SignInRequest,
    *,
    notify: Notify,
    launcher: BrowserLauncher = open_system_browser,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[SessionRecord]:
    """A session for one command (`--ephemeral-auth`): held in memory, no refresh token, gone when the block ends."""
    request = replace(request, persistent=False, signup=False)
    binding_key = settings.binding_key(persistent=False)
    store = MemoryCredentialStore()
    grant = await sign_in(settings, request, notify=notify, launcher=launcher, transport=transport)
    store.save(binding_key, SessionRecord.from_grant(grant, binding_key=binding_key))
    try:
        record = store.load(binding_key)
        if record is None:
            raise RuntimeError("the ephemeral session vanished before use")
        yield record
    finally:
        store.clear()
