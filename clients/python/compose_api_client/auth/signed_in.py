"""A session signed in as the person who ran `compose-api auth login`: the CLI's own credentials, for programs.

The CLI's API commands get their session here too (`cli/commands.py`, `make_session`), so a program and the CLI on the
same profile always carry the same credential.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TypeAlias

import httpx

from compose_api_client.auth import storage
from compose_api_client.auth.oauth import Auth0OAuthClient
from compose_api_client.auth.session import AuthSession
from compose_api_client.auth.sources import AsyncStoredSession, SyncStoredSession
from compose_api_client.auth.storage import CredentialStore
from compose_api_client.ext.credentials import TOKEN_ENV_VAR, AsyncTokenSource, EnvironmentToken, TokenSource
from compose_api_client.ext.errors import StorageError
from compose_api_client.ext.session import AsyncComposeSession, ComposeSession
from compose_api_client.profiles import Profile, load_profile

StoreOpener: TypeAlias = Callable[[Profile], CredentialStore]


def signed_in_session(
    profile: str | Profile | None = None,
    *,
    url: str | None = None,
    timeout: float = 300.0,
    open_store: StoreOpener | None = None,
    transport: httpx.BaseTransport | None = None,
    auth0_transport: httpx.AsyncBaseTransport | None = None,
) -> ComposeSession:
    """A session on `profile`'s API carrying the credential the CLI would. Use it as a context manager.

    `profile` is a name, chosen as `--profile` is (None: `COMPOSE_API_CLI_PROFILE`, else `production`), or a `Profile`
    already loaded. The credential is the first that applies:

    - none, when `url` names another API than the profile's: a profile's credentials go only to its own API;
    - `COMPOSE_API_TOKEN` from the environment (set but empty is a `UsageError`);
    - the profile's stored login, from `compose-api auth login`: renewed when it is about to expire (and once when the
      API refuses a read), the renewal saved back to the store for the CLI and every other program;
    - none, which the API allows: no login, a profile that cannot sign in, or a host with no credential store.

    A credential store that cannot be read (a locked keychain, an unusable record) raises `StorageError` when a request
    looks for the login; it never becomes an anonymous call. Nothing here prints or logs a token. `open_store` opens
    the credential store (default: the OS store); `transport` and `auth0_transport` replace the network to the API
    and to Auth0. A stored login is read on an event loop of its own for each request, so on a thread already running
    one (Jupyter, async code) use `async_signed_in_session`.
    """
    settings = _profile(profile)
    base_url, credential = _credential(settings, url, open_store)
    tokens: TokenSource | None = (
        SyncStoredSession(settings, credential, auth0_transport=auth0_transport)
        if isinstance(credential, AuthSession)
        else credential
    )
    return ComposeSession(base_url, tokens=tokens, timeout=timeout, ca_bundle=settings.ca_bundle, transport=transport)


@asynccontextmanager
async def async_signed_in_session(
    profile: str | Profile | None = None,
    *,
    url: str | None = None,
    timeout: float = 300.0,
    open_store: StoreOpener | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    auth0_transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[AsyncComposeSession]:
    """`signed_in_session`'s asynchronous twin, as an async context manager: the same profile, the same credential.

    It holds the connection to Auth0 that renewing a stored login needs for as long as the block runs.
    """
    settings = _profile(profile)
    base_url, credential = _credential(settings, url, open_store)
    async with AsyncExitStack() as stack:
        tokens: AsyncTokenSource | None = None
        if isinstance(credential, AuthSession):
            oauth = await stack.enter_async_context(Auth0OAuthClient(settings, transport=auth0_transport))
            tokens = AsyncStoredSession(credential, oauth, required=False)
        elif credential is not None:
            tokens = credential.as_async()
        yield await stack.enter_async_context(
            AsyncComposeSession(
                base_url, tokens=tokens, timeout=timeout, ca_bundle=settings.ca_bundle, transport=transport
            )
        )


def _profile(profile: str | Profile | None) -> Profile:
    return profile if isinstance(profile, Profile) else load_profile(profile).settings


def _credential(
    settings: Profile, url: str | None, open_store: StoreOpener | None
) -> tuple[str, EnvironmentToken | AuthSession | None]:
    """Where to send requests, and what with: the environment's token, the profile's stored login, or nothing."""
    if url is not None and not settings.matches_url(url):
        return url, None
    if TOKEN_ENV_VAR in os.environ:
        return settings.api_base_url, EnvironmentToken()
    return settings.api_base_url, _stored_login(settings, open_store)


def _stored_login(settings: Profile, open_store: StoreOpener | None) -> AuthSession | None:
    if settings.auth0_client_id is None:
        return None  # a profile that cannot sign in holds no login
    try:
        if open_store is not None:
            store = open_store(settings)
        else:
            store = storage.open_persistent_store(settings, check=False, writable=False)
    except StorageError:
        return None  # no supported credential store on this host
    try:
        return AuthSession(settings, store)
    except StorageError:
        if store.load(settings.binding_key(persistent=True)) is None:
            return None  # no saved login; an unusable state directory is not needed
        raise
