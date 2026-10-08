"""Auth profile precedence, URL checks, and credential binding. No network and no credential store."""

import logging
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from compose_api_client.cli.commands import Settings, app
from compose_api_client.cli.config import (
    AUTH0_ISSUER,
    ENV_AUDIENCE,
    ENV_PROFILE,
    ENV_SCOPES,
    ENV_URL,
    LOCAL_CLIENT_ID,
    PRODUCTION_CLIENT_ID,
    AuthOverrides,
    ConfigError,
    canonical_api_base_url,
    canonical_issuer,
    resolve_auth_profile,
)
from compose_api_client.ext import ComposeSession
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _quiet_httpx_logs() -> Iterator[None]:
    """httpx logs each request at INFO, and that record lands on CliRunner's stream after it has closed."""
    logger = logging.getLogger("httpx")
    level = logger.level
    logger.setLevel(logging.WARNING)
    yield
    logger.setLevel(level)


def test_builtin_profiles_do_not_share_a_binding(tmp_path: Path) -> None:
    production = resolve_auth_profile(environ={}, config_path=tmp_path / "missing.toml")
    local = resolve_auth_profile(AuthOverrides(profile="local"), environ={}, config_path=tmp_path / "missing.toml")
    assert production.client_id == PRODUCTION_CLIENT_ID
    assert local.client_id == LOCAL_CLIENT_ID
    assert production.issuer == local.issuer == AUTH0_ISSUER
    assert production.audience == "https://api.compose.cam.uchc.edu"
    assert local.audience == "https://api.compose.local"
    assert production.api_base_url == "https://compose.cam.uchc.edu"
    assert local.api_base_url == "https://api.compose-api-local"
    assert production.binding_key() != local.binding_key()
    assert production.jwks_url() == f"{AUTH0_ISSUER}.well-known/jwks.json"
    assert production.callback_urls() == (
        "http://127.0.0.1:51111/callback",
        "http://127.0.0.1:52111/callback",
        "http://127.0.0.1:53111/callback",
    )


def test_flag_beats_environment_beats_file_beats_default(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[profiles.production]\naudience = "https://from-file.example"\n', encoding="utf-8")
    from_env = resolve_auth_profile(environ={ENV_AUDIENCE: "https://from-env.example"}, config_path=path)
    assert from_env.audience == "https://from-env.example"
    assert from_env.sources["audience"] == f"env {ENV_AUDIENCE}"
    from_flag = resolve_auth_profile(
        AuthOverrides(audience="https://from-flag.example"),
        environ={ENV_AUDIENCE: "https://from-env.example"},
        config_path=path,
    )
    assert from_flag.audience == "https://from-flag.example"
    assert from_flag.sources["audience"] == "flag"
    from_file = resolve_auth_profile(environ={}, config_path=path)
    assert from_file.audience == "https://from-file.example"
    assert from_file.sources["audience"] == "file [profiles.production]"
    assert from_file.client_id == PRODUCTION_CLIENT_ID
    assert from_file.sources["client_id"] == "default"


def test_profile_flag_beats_environment(tmp_path: Path) -> None:
    resolved = resolve_auth_profile(
        AuthOverrides(profile="local"),
        environ={ENV_PROFILE: "production"},
        config_path=tmp_path / "missing.toml",
    )
    assert resolved.name == "local"
    assert resolved.sources["profile"] == "flag"
    assert resolved.client_id == LOCAL_CLIENT_ID


def test_custom_profile_does_not_inherit_another_profiles_client(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join([
            "[profiles.lab]",
            'issuer = "https://tenant.example/"',
            'audience = "https://api.lab.example"',
            'api_base_url = "https://api.lab.example"',
            "",
        ]),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="client_id"):
        resolve_auth_profile(AuthOverrides(profile="lab"), environ={}, config_path=path)


def test_url_override_does_not_reuse_credentials_for_a_different_api(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    with pytest.raises(ConfigError, match="other API"):
        resolve_auth_profile(environ={ENV_URL: "https://other.example"}, config_path=missing)
    same = resolve_auth_profile(environ={ENV_URL: "https://compose.cam.uchc.edu/"}, config_path=missing)
    assert same.api_base_url == "https://compose.cam.uchc.edu"
    assert same.client_id == PRODUCTION_CLIENT_ID
    moved = resolve_auth_profile(
        AuthOverrides(
            api_base_url="https://other.example/prefix",
            issuer="https://other.example/",
            client_id="OtherClient",
            audience="https://api.other.example",
        ),
        environ={},
        config_path=missing,
    )
    assert moved.api_base_url == "https://other.example/prefix"
    assert moved.binding_key() != resolve_auth_profile(environ={}, config_path=missing).binding_key()


def _explicit(api_base_url: str, *, scopes: str = "openid email", ports: str | None = None) -> AuthOverrides:
    return AuthOverrides(
        issuer="https://tenant.example/",
        client_id="Client",
        audience="https://api.example",
        api_base_url=api_base_url,
        scopes=scopes,
        callback_ports=ports,
    )


def test_path_prefix_and_scope_order_change_only_the_binding_fields(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    root = resolve_auth_profile(_explicit("https://api.example"), environ={}, config_path=missing)
    prefixed = resolve_auth_profile(_explicit("https://api.example/compose/"), environ={}, config_path=missing)
    assert prefixed.api_base_url == "https://api.example/compose"
    assert prefixed.binding_key() != root.binding_key()
    email_first = resolve_auth_profile(
        _explicit("https://api.example", scopes="email openid"), environ={}, config_path=missing
    )
    openid_first = resolve_auth_profile(
        _explicit("https://api.example", scopes="openid email"), environ={}, config_path=missing
    )
    assert email_first.binding_material() == openid_first.binding_material()
    ports = resolve_auth_profile(
        _explicit("https://api.example", scopes="openid email", ports="51111,52111"),
        environ={},
        config_path=missing,
    )
    assert ports.binding_key() == openid_first.binding_key()
    assert ports.callback_ports == (51111, 52111)


def test_lookalike_hosts_are_not_the_same_api() -> None:
    assert canonical_api_base_url("https://compose.example") != canonical_api_base_url("https://compose.example.evil")
    assert canonical_api_base_url("https://Compose.Example/API") == "https://compose.example/API"
    assert canonical_issuer("https://Tenant.Example") == "https://tenant.example/"
    with pytest.raises(ConfigError):
        canonical_api_base_url("https://127.1")
    with pytest.raises(ConfigError):
        canonical_api_base_url("http://compose.example")
    with pytest.raises(ConfigError):
        canonical_api_base_url("https://user:secret@compose.example")
    with pytest.raises(ConfigError):
        canonical_api_base_url("https://compose.example/a?x=1")
    with pytest.raises(ConfigError):
        canonical_api_base_url("https://compose.example/a#frag")
    with pytest.raises(ConfigError):
        canonical_issuer("http://127.0.0.1")
    assert canonical_api_base_url("http://127.0.0.1:8000/compose/") == "http://127.0.0.1:8000/compose"
    assert canonical_api_base_url("http://localhost:8000") == "http://localhost:8000"


def test_config_file_rejects_secrets_symlinks_and_group_writes(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[profiles.production]\naccess_token = "nope"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="secret"):
        resolve_auth_profile(environ={}, config_path=path)
    path.write_text('[profiles.production]\nclient_id = "eyJaaa.bbbb.cccc"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="token") as excinfo:
        resolve_auth_profile(environ={}, config_path=path)
    assert "eyJaaa" not in str(excinfo.value)
    path.write_text('[profiles.production]\nclient_id = "LabClient"\n', encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IWGRP)
    with pytest.raises(ConfigError, match="writable"):
        resolve_auth_profile(environ={}, config_path=path)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    link = tmp_path / "link.toml"
    link.symlink_to(path)
    with pytest.raises(ConfigError, match="symlink"):
        resolve_auth_profile(environ={}, config_path=link)
    with pytest.raises(ConfigError, match="unknown environment"):
        resolve_auth_profile(environ={"COMPOSE_API_AUTH0_SECRET": "x"}, config_path=path)
    kept = resolve_auth_profile(environ={"COMPOSE_API_TOKEN": "eyJaaa.bbbb.cccc"}, config_path=path)
    assert kept.client_id == "LabClient"


def test_scope_environment_and_manual_token_are_separate(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    resolved = resolve_auth_profile(environ={ENV_SCOPES: "openid"}, config_path=missing)
    assert resolved.scopes == frozenset({"openid"})
    baseline = resolve_auth_profile(environ={}, config_path=missing)
    assert resolved.binding_key() != baseline.binding_key()


def test_anonymous_command_does_not_read_the_profile_file(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_path: Path) -> None:
        raise AssertionError("auth config was read")

    monkeypatch.setattr("compose_api_client.cli.config._read_document", boom)
    seen: dict[str, Settings] = {}

    def make(settings: Settings) -> ComposeSession:
        seen["settings"] = settings
        return ComposeSession(settings.url, token=settings.token, transport=_ok())

    monkeypatch.setattr("compose_api_client.cli.commands.make_session", make)
    result = runner.invoke(app, ["--profile", "nope", "health"])
    assert result.exit_code == 0
    assert seen["settings"].auth_overrides.profile == "nope"
    flagged = runner.invoke(app, ["--url", "http://127.0.0.1:9", "--auth0-issuer", "https://tenant.example/", "health"])
    assert flagged.exit_code == 0
    assert seen["settings"].auth_overrides.api_base_url == "http://127.0.0.1:9"
    assert seen["settings"].auth_overrides.issuer == "https://tenant.example/"
    from_env = runner.invoke(app, ["health"], env={ENV_PROFILE: "local", ENV_URL: "http://127.0.0.1:9"})
    assert from_env.exit_code == 0
    assert seen["settings"].auth_overrides.profile is None
    assert seen["settings"].auth_overrides.api_base_url is None


def test_help_and_base_import_do_not_load_the_server_or_a_credential_store() -> None:
    script = (
        "import compose_api_client, compose_api_client.cli, sys\n"
        "assert 'compose_api' not in sys.modules\n"
        "assert 'compose_api.config' not in sys.modules\n"
        "assert 'keyring' not in sys.modules\n"
    )
    completed = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True)  # noqa: S603
    assert completed.returncode == 0, completed.stderr
    help_text = runner.invoke(app, ["--help"])
    assert help_text.exit_code == 0
    assert "COMPOSE_API_AUTH0_ISSUER" in help_text.stdout
    assert "COMPOSE_API_TOKEN" in help_text.stdout


def _ok() -> httpx.MockTransport:
    return httpx.MockTransport(lambda _request: httpx.Response(200, json={"docs": "x/docs", "version": "0.6.0"}))
