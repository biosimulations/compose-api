"""The API boundary: the generated client against the real app over ASGI, carrying real signed tokens."""

import asyncio
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from compose_api_client.auth.models import SessionRecord
from compose_api_client.auth.storage import SERVICE, MemoryCredentialStore
from compose_api_client.cli.commands import main
from compose_api_client.cli.wiring import Wiring
from compose_api_client.ext.errors import (
    ExitCode,
    StorageError,
)
from compose_api_client.profiles import CliSettings

from tests.fixtures.auth_fixtures import AUTH0_TEST_DOMAIN, AUTH0_TEST_ISSUER
from tests.fixtures.cli_fixtures import (
    DESCRIPTION_CANARY,
    REFRESH_TOKEN,
    FakeBrowser,
    FakeComposeApi,
    FakeCredentialManager,
    FakeTenant,
    RecordingTransport,
    cli_settings,
    seed_session,
    use_profile,
    wire,
    write_cli_config,
)

API = "https://api.compose.test"


def _settings(**overrides: Any) -> CliSettings:
    return cli_settings(callback_port=8400, **overrides)


def _archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.xml", "<omexManifest/>")
    return buffer.getvalue()


# Commands, end to end through main().


@pytest.fixture
def stored(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
) -> MemoryCredentialStore:
    """A signed-in profile whose commands reach the fake tenant and the real app over ASGI."""
    settings = _settings()
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    asyncio.run(seed_session(settings, fake_tenant, store))
    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: store,
            auth0_transport=fake_tenant.transport,
            api_transport=fake_compose_api.transport,
        ),
    )
    return store


def _bearers(transport: RecordingTransport) -> list[str | None]:
    return [request.headers.get("authorization") for request in transport.requests]


def test_simulators_list_uses_the_stored_session(
    stored: MemoryCredentialStore, fake_compose_api: FakeComposeApi, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["-o", "table", "simulators", "list"]) == ExitCode.OK
    table = capsys.readouterr().out
    assert str(FakeComposeApi.SIMULATOR_ID) in table and "0123456789" in table
    assert main(["simulators", "list", "--json"]) == ExitCode.OK
    document = json.loads(capsys.readouterr().out)
    assert [version["database_id"] for version in document["versions"]] == [FakeComposeApi.SIMULATOR_ID]
    bearers = _bearers(fake_compose_api.transport)
    assert len(bearers) == 2 and all(b is not None and b.startswith("Bearer ey") for b in bearers)


def test_status_of_a_run_and_of_one_without_a_job_yet(
    stored: MemoryCredentialStore, fake_compose_api: FakeComposeApi, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status", str(FakeComposeApi.SIMULATION_ID), "--json"]) == ExitCode.OK
    record = json.loads(capsys.readouterr().out)
    assert (record["simulation_id"], record["status"]) == (FakeComposeApi.SIMULATION_ID, "running")
    # A 404 from the status route means no SLURM job exists yet: `status` reports "submitting" (docs/cli.md).
    assert main(["status", "999", "--json"]) == ExitCode.OK
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "submitting"
    assert DESCRIPTION_CANARY not in captured.out + captured.err


def test_run_uploads_the_archive_once_and_reports_its_ids(
    stored: MemoryCredentialStore,
    fake_compose_api: FakeComposeApi,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = tmp_path / "experiment.omex"
    archive.write_bytes(_archive())
    assert main(["run", str(archive), "--interval", "2.5", "--batch", "--json"]) == ExitCode.OK
    document = json.loads(capsys.readouterr().out)
    assert document["simulation_database_id"] == FakeComposeApi.SIMULATION_ID
    assert "complete" not in json.dumps(document).lower(), "a submission is a reference, not a result"
    [upload] = fake_compose_api.uploads
    assert (upload["content"], upload["batch"]) == (archive.read_bytes(), True)
    [request] = fake_compose_api.transport.requests
    assert request.url.path == "/simulation/run"
    assert request.headers["authorization"].startswith("Bearer ey")


@pytest.mark.parametrize("contents", [b"", b"not a zip archive"], ids=["empty", "not-zip"])
def test_run_checks_the_archive_before_anything_else(
    stored: MemoryCredentialStore,
    fake_compose_api: FakeComposeApi,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    contents: bytes,
) -> None:
    archive = tmp_path / "experiment.omex"
    archive.write_bytes(contents)
    assert main(["run", str(archive), "--json"]) == ExitCode.USAGE
    error = json.loads(capsys.readouterr().out)["error"]
    assert (error["category"], error["exit_code"]) == ("usage", int(ExitCode.USAGE))
    assert "nothing was uploaded" in error["message"]
    assert fake_compose_api.transport.requests == []


def test_run_of_a_missing_archive_is_a_usage_error(
    stored: MemoryCredentialStore,
    fake_compose_api: FakeComposeApi,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["run", str(tmp_path / "missing.omex")]) == ExitCode.USAGE
    assert "does not exist" in capsys.readouterr().err
    assert fake_compose_api.transport.requests == []


ANONYMOUS_COMMANDS = [["simulators", "list"], ["status", "41"], ["run", "{archive}"]]


@pytest.mark.parametrize("argv", ANONYMOUS_COMMANDS)
def test_without_a_session_api_commands_call_anonymously_and_never_sign_in(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    tmp_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    argv: list[str],
) -> None:
    """The API allows anonymous calls, so no session means an anonymous call; it never means a sign-in."""
    archive = tmp_path / "experiment.omex"
    archive.write_bytes(_archive())
    use_profile(monkeypatch, _settings())
    browser = FakeBrowser(fake_tenant)
    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: MemoryCredentialStore(),
            launcher=browser,
            auth0_transport=fake_tenant.transport,
            api_transport=fake_compose_api.transport,
        ),
    )
    assert main([part.format(archive=archive) for part in argv]) == ExitCode.OK
    assert browser.urls == [] and fake_tenant.forms(FakeTenant.TOKEN) == []
    assert fake_compose_api.transport.requests and set(_bearers(fake_compose_api.transport)) == {None}


def test_api_commands_call_anonymously_when_the_host_has_no_credential_store(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_compose_api: FakeComposeApi,
) -> None:
    """No supported OS store means no stored session can exist: there is nothing to fall back from."""
    use_profile(monkeypatch, _settings())

    def unsupported(_settings: CliSettings) -> MemoryCredentialStore:
        raise StorageError("Unsupported OS credential backend; use --ephemeral-auth")

    wire(monkeypatch, Wiring(store_factory=unsupported, api_transport=fake_compose_api.transport))
    assert main(["simulators", "list", "--json"]) == ExitCode.OK
    assert set(_bearers(fake_compose_api.transport)) == {None}


class _LockedStore(MemoryCredentialStore):
    def load(self, binding_key: str) -> SessionRecord | None:
        raise StorageError("the OS credential store is locked; unlock it, or use --ephemeral-auth")


def test_an_unreadable_store_is_an_error_never_an_anonymous_call(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A store that exists but cannot be read may hold a session: calling anonymously instead could, for example,
    submit an unowned run in place of the person's own. Nothing is sent."""
    use_profile(monkeypatch, _settings())
    wire(monkeypatch, Wiring(store_factory=lambda _settings: _LockedStore(), api_transport=fake_compose_api.transport))
    assert main(["simulators", "list", "--json"]) == ExitCode.CONFIG
    error = json.loads(capsys.readouterr().out)["error"]
    assert (error["category"], error["exit_code"]) == ("storage", int(ExitCode.CONFIG))
    assert "--ephemeral-auth" in error["message"]
    assert fake_compose_api.transport.requests == []


def test_unusable_state_path_calls_anonymously_only_when_no_session_is_saved(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from compose_api_client.auth import state as state_module

    real_state = tmp_path / "real-state"
    real_state.mkdir(mode=0o700)
    link_state = tmp_path / "symlink-state"
    link_state.symlink_to(real_state, target_is_directory=True)
    monkeypatch.setattr(state_module, "user_state_path", lambda _app: link_state)

    settings = _settings()
    use_profile(monkeypatch, settings)
    records: dict[str, SessionRecord] = {}

    class _CustomStore:
        def load(self, binding_key: str) -> SessionRecord | None:
            return records.get(binding_key)

        def save(self, binding_key: str, value: SessionRecord) -> None:
            records[binding_key] = value

        def delete(self, binding_key: str) -> bool:
            return records.pop(binding_key, None) is not None

    wire(monkeypatch, Wiring(store_factory=lambda _s: _CustomStore(), api_transport=fake_compose_api.transport))
    # No saved login: a symlinked state path does not block anonymous API commands.
    assert main(["simulators", "list", "--json"]) == ExitCode.OK
    assert _bearers(fake_compose_api.transport) == [None]

    # Saved login present: refusing the symlinked state path is an error, never a silent downgrade to anonymous.
    seeded = MemoryCredentialStore()
    record = asyncio.run(seed_session(settings, fake_tenant, seeded))
    records[settings.binding_key(persistent=True)] = record
    capsys.readouterr()
    assert main(["simulators", "list", "--json"]) == ExitCode.CONFIG
    error = json.loads(capsys.readouterr().out)["error"]
    assert (error["category"], error["exit_code"]) == ("storage", int(ExitCode.CONFIG))
    assert len(fake_compose_api.transport.requests) == 1


def test_a_profile_that_cannot_sign_in_calls_anonymously(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_compose_api: FakeComposeApi,
) -> None:
    write_cli_config(
        cli_config_path,
        f'[profiles.dev]\napi_base_url = "{API}"\nauth0_domain = "{AUTH0_TEST_DOMAIN}"\n'
        'auth0_audience = "https://api.compose.test"\n',
    )

    def never(_settings: CliSettings) -> MemoryCredentialStore:
        raise AssertionError("a profile without a client ID has no session to look for")

    wire(monkeypatch, Wiring(store_factory=never, api_transport=fake_compose_api.transport))
    assert main(["--profile", "dev", "simulators", "list", "--json"]) == ExitCode.OK
    assert set(_bearers(fake_compose_api.transport)) == {None}


@pytest.mark.parametrize("device", [False, True], ids=["browser", "device"])
def test_ephemeral_auth_signs_in_for_one_command_and_keeps_nothing(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
    device: bool,
) -> None:
    use_profile(monkeypatch, cli_settings())

    def no_store(_settings: CliSettings) -> MemoryCredentialStore:
        raise AssertionError("--ephemeral-auth never opens the persistent store")

    if device:
        fake_tenant.queue(FakeTenant.DEVICE, fake_tenant.device_response(interval=1))
        fake_tenant.queue(FakeTenant.TOKEN, fake_tenant.token_response())
    wire(
        monkeypatch,
        Wiring(
            store_factory=no_store,
            launcher=FakeBrowser(fake_tenant),
            auth0_transport=fake_tenant.transport,
            api_transport=fake_compose_api.transport,
        ),
    )
    argv = ["--ephemeral-auth", *(["--device"] if device else []), "simulators", "list", "--json"]
    assert main(argv) == ExitCode.OK
    assert json.loads(capsys.readouterr().out)["versions"][0]["database_id"] == FakeComposeApi.SIMULATOR_ID
    [request] = fake_compose_api.transport.requests
    assert request.headers["authorization"].startswith("Bearer ey")
    scope = (fake_tenant.forms(FakeTenant.DEVICE)[0] if device else fake_tenant.authorize_requests[0])["scope"]
    assert "offline_access" not in scope


def test_ephemeral_auth_refuses_another_api_or_a_second_credential(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_network_or_browser: list[str],
) -> None:
    use_profile(monkeypatch, _settings())  # a fixed port: finding a free one would bind a socket
    assert main(["--url", "https://elsewhere.example", "--ephemeral-auth", "simulators", "list"]) == ExitCode.USAGE
    assert "--url names another API" in capsys.readouterr().err
    monkeypatch.setenv("COMPOSE_API_TOKEN", "env-token-value")
    assert main(["--ephemeral-auth", "simulators", "list"]) == ExitCode.USAGE
    captured = capsys.readouterr()
    assert "both supply credentials" in captured.err and "env-token-value" not in captured.out + captured.err


def test_login_is_confirmed_by_the_api(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = cli_settings()
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: store,
            launcher=FakeBrowser(fake_tenant),
            auth0_transport=fake_tenant.transport,
            api_transport=fake_compose_api.transport,
        ),
    )
    assert main(["-o", "table", "auth", "login"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert f"Identity: {fake_tenant.subject} ({AUTH0_TEST_ISSUER})" in out
    assert "API: confirmed this identity just now" in out
    assert fake_compose_api.transport.paths() == ["/auth/me"]
    record = store.load(settings.binding_key(persistent=True))
    assert record is not None and record.api_verified_at is not None and record.refresh_token is not None
    assert record.refresh_token.get_secret_value() == REFRESH_TOKEN


def test_login_on_windows_keeps_the_session_in_one_credential_manager_item(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    windows_credential_manager: FakeCredentialManager,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The store the CLI selects for itself on Windows: keyring's backend probes it, the session is one item holding the
    record as UTF-8 (#320), and `auth status` reads it back."""
    from compose_api_client.auth import state as state_module

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
    assert main(["auth", "login", "--json"]) == ExitCode.OK
    items = windows_credential_manager.items
    assert list(items) == [f"{SERVICE}.{settings.binding_key(persistent=True)}"], "the probe left nothing behind"
    [item] = items.values()
    assert json.loads(item["CredentialBlob"].removesuffix(b"\0").decode("ascii"))["refresh_token"] == REFRESH_TOKEN
    capsys.readouterr()
    assert main(["auth", "status", "--json"]) == ExitCode.OK
    status = json.loads(capsys.readouterr().out)
    assert status["state"] == "valid" and status["identity"]["subject"] == fake_tenant.subject


@pytest.mark.parametrize("failure", ["unreachable", "404"])
def test_an_unreachable_api_after_login_keeps_the_session_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    settings = cli_settings()
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()

    def unreachable(_request: httpx.Request) -> httpx.Response:
        if failure == "404":
            return httpx.Response(404)
        raise httpx.ConnectError("refused")

    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: store,
            launcher=FakeBrowser(fake_tenant),
            auth0_transport=fake_tenant.transport,
            api_transport=httpx.MockTransport(unreachable),
        ),
    )
    assert main(["auth", "login", "--json"]) == (ExitCode.NETWORK if failure == "unreachable" else ExitCode.FAILURE)
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["category"] == ("network" if failure == "unreachable" else "not_found")
    assert error["message"].startswith("signed in and saved the session, but the Compose API did not confirm it")
    assert "auth status --verify" in error["message"]
    record = store.load(settings.binding_key(persistent=True))
    assert record is not None and record.api_verified_at is None


def test_status_is_local_until_asked_to_verify(
    stored: MemoryCredentialStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["-o", "table", "auth", "status"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "API: never confirmed" in out
    assert main(["auth", "status", "--verify", "--json"]) == ExitCode.OK
    document = json.loads(capsys.readouterr().out)
    assert document["checked_with_api"] is True and document["api_verified_at"] is not None
    assert main(["-o", "table", "auth", "status"]) == ExitCode.OK
    assert "API: last confirmed" in capsys.readouterr().out
    assert main(["auth", "status", "--json"]) == ExitCode.OK
    assert json.loads(capsys.readouterr().out)["checked_with_api"] is False


def test_a_failed_verification_is_not_a_sign_out(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings()
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    before = asyncio.run(seed_session(settings, fake_tenant, store))

    def unreachable(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    wire(
        monkeypatch,
        Wiring(
            store_factory=lambda _settings: store,
            auth0_transport=fake_tenant.transport,
            api_transport=httpx.MockTransport(unreachable),
        ),
    )
    assert main(["auth", "status", "--verify"]) == ExitCode.NETWORK
    assert "This is not a sign-out" in capsys.readouterr().err
    assert store.load(settings.binding_key(persistent=True)) == before


def test_verify_without_a_session_contacts_nothing(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_network_or_browser: list[str],
) -> None:
    use_profile(monkeypatch, _settings())
    api = RecordingTransport(httpx.MockTransport(lambda _request: httpx.Response(200)))
    wire(monkeypatch, Wiring(store_factory=lambda _settings: MemoryCredentialStore(), api_transport=api))
    assert main(["-o", "table", "auth", "status", "--verify"]) == ExitCode.AUTH_REQUIRED
    assert "No session" in capsys.readouterr().out
    assert api.requests == []
