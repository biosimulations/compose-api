"""Choosing a sign-in flow, and keeping its result only once it is fully validated."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx

from compose_api_client.auth.browser import BrowserLauncher, auto_method, browser_sign_in, open_system_browser
from compose_api_client.auth.device import device_sign_in
from compose_api_client.auth.models import Notify, Provider, SessionRecord, SignInMethod, SignInRequest, TokenGrant
from compose_api_client.auth.oauth import Auth0OAuthClient
from compose_api_client.auth.session import AuthSession
from compose_api_client.auth.storage import CredentialStore, MemoryCredentialStore
from compose_api_client.ext.errors import ConfigError
from compose_api_client.profiles import CliSettings


def resolve(settings: CliSettings, request: SignInRequest, *, notify: Notify) -> SignInRequest:
    """`request` with `AUTO` replaced by the method it means here, telling the person why when that is anything but the
    browser on this computer's desktop.

    Whoever starts a sign-in resolves it once, first: `auth signup`/`auth login` (`sign_in_command`), to check the
    provider before touching the credential store, and `sign_in` for everyone else. A request that names its method
    passes through unchanged and silently, so the environment is read once and the flows only see a chosen method.
    """
    if request.method is not SignInMethod.AUTO:
        return request
    method, note = auto_method(settings.callback_port)
    if note is not None:
        notify(note)
    return replace(request, method=method)


def connection_for(settings: CliSettings, request: SignInRequest) -> str | None:
    """The Auth0 connection to steer the browser to. Raises before anything touches the network or a browser.

    The request's method must be resolved (`resolve`). The device endpoint takes no connection, so with the device
    method the person picks the provider on the hosted page.
    """
    if request.method is SignInMethod.AUTO:
        raise ValueError("resolve the sign-in method before choosing a connection")
    if request.method is SignInMethod.DEVICE:
        return None
    if request.provider is Provider.GOOGLE:
        if settings.google_connection is None:
            raise ConfigError(
                f"--provider google needs google_connection set for profile {settings.profile!r}: the tenant's"
                " Google connection name, often google-oauth2. Or sign in with --method device and choose Google there"
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
    """Run the browser or device flow the request asks for. Never switches from one to the other on failure.

    An `AUTO` request is resolved here unless its caller already did (`resolve`): the flows only see a chosen method.
    """
    resolved = resolve(settings, request, notify=notify)
    connection = connection_for(settings, resolved)
    async with Auth0OAuthClient(settings, transport=transport) as client:
        if resolved.method is SignInMethod.DEVICE:
            return await device_sign_in(client, resolved, notify=notify)
        return await browser_sign_in(client, resolved, connection=connection, launcher=launcher, notify=notify)


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
        async with Auth0OAuthClient(settings, transport=transport) as client:
            return await session.commit(grant, snapshot, client=client)


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
