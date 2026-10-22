"""Environment credentials through the installed CLI command boundary."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from compose_api_client.auth.storage import MemoryCredentialStore
from compose_api_client.cli.commands import main
from compose_api_client.cli.wiring import Wiring

from tests.fixtures.cli_fixtures import (
    FakeComposeApi,
    FakeTenant,
    RecordingTransport,
    cli_settings,
    seed_session,
    use_profile,
    wire,
)


def configure(
    monkeypatch: pytest.MonkeyPatch,
    tenant: FakeTenant,
    transport: httpx.AsyncBaseTransport,
) -> str:
    settings = cli_settings(callback_port=8400)
    use_profile(monkeypatch, settings)
    store = MemoryCredentialStore()
    record = asyncio.run(seed_session(settings, tenant, store))
    token = record.access_token.get_secret_value()
    monkeypatch.setenv("COMPOSE_API_TOKEN", token)
    wire(monkeypatch, Wiring(store_factory=lambda _: store, auth0_transport=tenant.transport, api_transport=transport))
    return token


def test_environment_token_wins_over_stored_session(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stored_token = configure(monkeypatch, fake_tenant, fake_compose_api.transport)
    # A different, valid token makes precedence observable in the request.
    token = fake_tenant.token_response(subject="auth0|automation")["access_token"]
    assert isinstance(token, str) and token != stored_token
    monkeypatch.setenv("COMPOSE_API_TOKEN", token)
    assert main(["simulators", "list", "--json"]) == 0
    captured = capsys.readouterr()
    assert len(captured.err.strip().splitlines()) == 1
    assert "using COMPOSE_API_TOKEN from the environment instead of a stored session" in captured.err
    [request] = fake_compose_api.transport.requests
    assert request.headers["authorization"] == f"Bearer {token}"
    assert token not in captured.out + captured.err
    assert fake_tenant.requests == []


@pytest.mark.parametrize("command", [["auth", "status"], ["config", "show"]])
@pytest.mark.parametrize("json_output", [False, True])
def test_status_and_config_never_print_environment_token(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
    json_output: bool,
) -> None:
    token = configure(monkeypatch, fake_tenant, fake_compose_api.transport)
    assert main(["-o", "json" if json_output else "table", *command, *(["--json"] if json_output else [])]) == 0
    captured = capsys.readouterr()
    assert token not in captured.out + captured.err
    if command[0] == "auth":
        assert "environment (COMPOSE_API_TOKEN)" in captured.out
        if json_output:
            assert json.loads(captured.out)["state"] == "unverified"
    assert fake_tenant.requests == fake_compose_api.transport.requests == []


@pytest.mark.parametrize("command", [["simulators", "list"], ["auth", "status", "--verify"]])
def test_rejected_environment_token_names_variable_and_never_renews(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    transport = RecordingTransport(httpx.MockTransport(lambda _: httpx.Response(401)))
    token = configure(monkeypatch, fake_tenant, transport)
    assert main([*command, "--json"]) == 3
    captured = capsys.readouterr()
    assert "COMPOSE_API_TOKEN" in json.loads(captured.out)["error"]["message"]
    assert token not in captured.out + captured.err
    assert len(transport.requests) == 1 and fake_tenant.requests == []


@pytest.mark.parametrize("token", ["", "   ", "\t\n"])
def test_empty_environment_token_is_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    token: str,
) -> None:
    configure(monkeypatch, fake_tenant, fake_compose_api.transport)
    monkeypatch.setenv("COMPOSE_API_TOKEN", token)
    assert main(["simulators", "list"]) == 2
    assert fake_compose_api.transport.requests == fake_tenant.requests == []


def test_environment_token_is_not_sent_to_url_override(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = configure(monkeypatch, fake_tenant, fake_compose_api.transport)
    assert main(["--url", "https://other.example", "simulators", "list"]) == 0
    captured = capsys.readouterr()
    assert "calling anonymously without COMPOSE_API_TOKEN" in captured.err
    [request] = fake_compose_api.transport.requests
    assert request.url.host == "other.example" and "authorization" not in request.headers
    assert token not in captured.out + captured.err


def test_environment_status_is_valid_only_after_api_verification(
    monkeypatch: pytest.MonkeyPatch,
    cli_config_path: Path,
    fake_tenant: FakeTenant,
    fake_compose_api: FakeComposeApi,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = configure(monkeypatch, fake_tenant, fake_compose_api.transport)
    assert main(["auth", "status", "--verify", "--json"]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["state"] == "valid" and result["checked_with_api"] is True
    assert result["identity"]["subject"] == fake_tenant.subject
    assert fake_compose_api.transport.paths() == ["/auth/me"]
    assert token not in captured.out + captured.err
