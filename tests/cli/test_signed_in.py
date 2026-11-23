"""`auth.signed_in_session` and its async twin: a program calls the API as the person signed in with the CLI.

The login is the real one (a sign-in through `main()`, or `seed_session`'s journaled commit), read back through the
real profile resolution, credential store and renewal; only Auth0 and the network are the fakes the CLI's own tests
use. The API is the real app over ASGI, verifying the tokens it is sent. Every test runs both twins: the synchronous
session, and the asynchronous one inside a running event loop.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from compose_api_client.auth import MemoryCredentialStore, async_signed_in_session, signed_in_session
from compose_api_client.auth import state as state_module
from compose_api_client.auth.signed_in import StoreOpener
from compose_api_client.cli.commands import main
from compose_api_client.cli.wiring import Wiring
from compose_api_client.ext import ExitCode, UsageError

from tests.fixtures.auth_fixtures import AUTH0_TEST_ISSUER
from tests.fixtures.cli_fixtures import (
    FakeBrowser,
    FakeComposeApi,
    FakeCredentialManager,
    FakeTenant,
    cli_settings,
    seed_session,
    use_profile,
    wire,
    write_cli_config,
)

pytestmark = pytest.mark.parametrize("kind", ["sync", "async"])


@pytest.fixture(autouse=True)
def no_environment_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COMPOSE_API_TOKEN", raising=False)


def call(
    kind: str,
    api: FakeComposeApi,
    tenant: FakeTenant,
    method: str,
    profile: str | None = None,
    *,
    url: str | None = None,
    open_store: StoreOpener | None = None,
) -> Any:
    """`method` on a session from the `kind` twin, opened and closed around the one call."""
    if kind == "sync":
        with signed_in_session(
            profile, url=url, open_store=open_store, transport=api.sync_transport, auth0_transport=tenant.transport
        ) as session:
            return getattr(session, method)()

    async def in_a_running_loop() -> Any:
        async with async_signed_in_session(
            profile, url=url, open_store=open_store, transport=api.transport, auth0_transport=tenant.transport
        ) as session:
            return await getattr(session, method)()

    return asyncio.run(in_a_running_loop())


def test_a_program_calls_as_the_person_the_cli_signed_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    windows_credential_manager: FakeCredentialManager,
    kind: str,
) -> None:
    """`compose-api auth login` keeps the session in the OS credential store; with no store given, a program's session
    finds it there under the same profile and binding, and sends it to that profile's API."""
    settings = cli_settings()
    use_profile(monkeypatch, settings)
    monkeypatch.setattr(state_module, "user_state_path", lambda _app: tmp_path / "state")
    wire(
        monkeypatch,
        Wiring(
            launcher=FakeBrowser(fake_tenant),
            auth0_transport=fake_tenant.transport,
            api_transport=fake_compose_api.transport,
        ),
    )
    assert main(["-o", "json", "auth", "login", "--method", "browser"]) == ExitCode.OK
    [item] = windows_credential_manager.items.values()
    access_token = json.loads(item["CredentialBlob"].removesuffix(b"\0").decode("ascii"))["access_token"]
    fake_compose_api.transport.requests.clear()
    auth0_requests = len(fake_tenant.requests)

    principal = call(kind, fake_compose_api, fake_tenant, "whoami")

    assert (principal.issuer, principal.subject) == (AUTH0_TEST_ISSUER, fake_tenant.subject)
    [request] = fake_compose_api.transport.requests
    assert str(request.url) == f"{settings.api_base_url}/auth/me"
    assert request.headers["authorization"] == f"Bearer {access_token}"
    assert len(fake_tenant.requests) == auth0_requests, "a valid login needs nothing from Auth0"


def test_the_profile_is_chosen_as_the_cli_chooses_it(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    kind: str,
) -> None:
    """A name, else `COMPOSE_API_CLI_PROFILE`, else `production`; and each profile's login is its own."""
    settings = cli_settings(profile="lab", callback_port=8400)
    fields = ("api_base_url", "auth0_domain", "auth0_audience", "auth0_client_id")
    write_cli_config(cli_config_path, "[profiles.lab]\n" + "".join(f'{f} = "{getattr(settings, f)}"\n' for f in fields))
    store = MemoryCredentialStore()
    record = asyncio.run(seed_session(settings, fake_tenant, store))

    def bearer(profile: str | None = None) -> str | None:
        call(kind, fake_compose_api, fake_tenant, "simulators", profile, open_store=lambda _profile: store)
        sent: str | None = fake_compose_api.transport.requests.pop().headers.get("authorization")
        return sent

    signed_in = f"Bearer {record.access_token.get_secret_value()}"
    assert bearer("lab") == signed_in
    assert bearer() is None, "the default profile is production, which has no login here"
    monkeypatch.setenv("COMPOSE_API_CLI_PROFILE", "lab")
    assert bearer() == signed_in
    assert bearer("production") is None
    assert fake_tenant.requests == []


def test_an_expiring_login_is_renewed_and_saved_for_the_cli(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    kind: str,
) -> None:
    settings = cli_settings(callback_port=8400)
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    first = asyncio.run(seed_session(settings, fake_tenant, store, expires_in=30))
    fake_tenant.queue(
        FakeTenant.TOKEN,
        fake_tenant.token_response(refresh_token="rt-rotated", include_id_token=False),  # noqa: S106 -- test data
    )

    call(kind, fake_compose_api, fake_tenant, "whoami", open_store=lambda _profile: store)

    [refresh] = fake_tenant.forms(FakeTenant.TOKEN)
    assert refresh["grant_type"] == "refresh_token"
    renewed = store.load(settings.binding_key(persistent=True))
    assert renewed is not None and renewed.generation == first.generation + 1
    assert renewed.refresh_token is not None and renewed.refresh_token.get_secret_value() == "rt-rotated"
    [request] = fake_compose_api.transport.requests
    assert request.headers["authorization"] == f"Bearer {renewed.access_token.get_secret_value()}", (
        "the renewed token is sent, not the one about to expire"
    )


def test_the_environment_token_comes_first_and_the_store_is_never_opened(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    kind: str,
) -> None:
    use_profile(monkeypatch, cli_settings(callback_port=8400))
    token = fake_tenant.token_response(subject="auth0|automation")["access_token"]
    monkeypatch.setenv("COMPOSE_API_TOKEN", token)

    def never(_profile: object) -> MemoryCredentialStore:
        raise AssertionError("COMPOSE_API_TOKEN is used without looking for a stored login")

    principal = call(kind, fake_compose_api, fake_tenant, "whoami", open_store=never)

    assert principal.subject == "auth0|automation"
    [request] = fake_compose_api.transport.requests
    assert request.headers["authorization"] == f"Bearer {token}"
    assert fake_tenant.requests == []


@pytest.mark.parametrize("token", ["", "  \t"])
def test_an_empty_environment_token_is_a_usage_error_never_an_anonymous_call(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    kind: str,
    token: str,
) -> None:
    use_profile(monkeypatch, cli_settings(callback_port=8400))
    monkeypatch.setenv("COMPOSE_API_TOKEN", token)
    with pytest.raises(UsageError, match="COMPOSE_API_TOKEN must not be empty"):
        call(kind, fake_compose_api, fake_tenant, "simulators")
    assert fake_compose_api.transport.requests == fake_tenant.requests == []


@pytest.mark.parametrize("credential", ["stored", "environment"])
@pytest.mark.parametrize(
    ("url", "host"),
    [("https://other.example", "other.example"), ("HTTPS://API.compose.test:443/", "api.compose.test")],
    ids=["another-api", "the-profiles-api-spelled-differently"],
)
def test_credentials_go_only_to_the_profiles_own_api(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    kind: str,
    credential: str,
    url: str,
    host: str,
) -> None:
    settings = cli_settings(callback_port=8400)
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    record = asyncio.run(seed_session(settings, fake_tenant, store))
    token = record.access_token.get_secret_value()
    if credential == "environment":
        token = fake_tenant.token_response(subject="auth0|automation")["access_token"]
        monkeypatch.setenv("COMPOSE_API_TOKEN", token)

    call(kind, fake_compose_api, fake_tenant, "simulators", url=url, open_store=lambda _profile: store)

    [request] = fake_compose_api.transport.requests
    assert request.url.host == host
    if host == "other.example":
        assert "authorization" not in request.headers
    else:
        assert request.headers["authorization"] == f"Bearer {token}"


def test_without_a_login_the_session_is_anonymous_and_never_signs_in(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    kind: str,
) -> None:
    use_profile(monkeypatch, cli_settings(callback_port=8400))
    call(kind, fake_compose_api, fake_tenant, "simulators", open_store=lambda _profile: MemoryCredentialStore())
    [request] = fake_compose_api.transport.requests
    assert "authorization" not in request.headers
    assert fake_tenant.requests == []


def test_a_host_without_a_supported_credential_store_calls_anonymously(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    kind: str,
) -> None:
    """The default store on a host whose keyring is not a supported OS store (`no_os_keyring` gives keyring's refusing
    `fail` backend): there is no login to find, so the call is anonymous, not an error."""
    use_profile(monkeypatch, cli_settings(callback_port=8400))
    call(kind, fake_compose_api, fake_tenant, "simulators")
    [request] = fake_compose_api.transport.requests
    assert "authorization" not in request.headers
    assert fake_tenant.requests == []
