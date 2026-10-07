"""Public CLI profiles: precedence, provenance, validation, and the binding that keeps sessions apart."""

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from compose_api.cli.config import (
    BUILTIN_PROFILES,
    DEFAULT_CALLBACK_PORT,
    OFFLINE_ACCESS_SCOPE,
    PROFILE_FIELDS,
    CliSettings,
    LoadedSettings,
    load_cli_settings,
    requested_scopes,
)
from compose_api.cli.errors import ConfigError
from compose_api.common.gateway.models import ServerMode
from compose_api.config import REPO_ROOT
from tests.fixtures.cli_fixtures import write_cli_config

CLIENT_ID = "AbCdEf0123456789AbCdEf0123456789"
LEAK_CANARY = "do-not-print-7f3a9c"
KUSTOMIZE = Path(REPO_ROOT) / "kustomize"


def _load(
    tmp_path: Path, config: str | None = None, *, env: dict[str, str] | None = None, profile: str | None = None
) -> LoadedSettings:
    path = tmp_path / "config.toml"
    if config is not None:
        write_cli_config(path, config)
    return load_cli_settings(profile, environ=env or {}, config_path=path)


def _config_error(tmp_path: Path, config: str | None = None, **kwargs: Any) -> str:
    with pytest.raises(ConfigError) as caught:
        _load(tmp_path, config, **kwargs)
    return caught.value.message


def _settings(**overrides: Any) -> CliSettings:
    values: dict[str, Any] = {
        "profile": "test",
        "api_base_url": "https://compose.example.org",
        "auth0_domain": "tenant.example.auth0.com",
        "auth0_audience": "https://api.compose.example.org",
        "auth0_client_id": CLIENT_ID,
    }
    return CliSettings(**{**values, **overrides})


def _read_env(path: Path) -> dict[str, str]:
    lines = [line for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    return dict(line.split("=", 1) for line in lines)


@pytest.mark.parametrize("name", ["production", "local"])
def test_builtin_profiles_need_no_file(tmp_path: Path, name: str) -> None:
    loaded = _load(tmp_path, profile=name)
    settings = loaded.settings
    assert settings.api_base_url == BUILTIN_PROFILES[name]["api_base_url"]
    assert settings.auth0_client_id is None, "no native application ID has been published yet"
    assert settings.issuer == f"https://{settings.auth0_domain}/"
    assert settings.redirect_uri == f"http://127.0.0.1:{DEFAULT_CALLBACK_PORT}/callback"
    assert loaded.config_found is False
    assert loaded.sources["api_base_url"] == loaded.sources["callback_port"] == "default"
    assert loaded.sources["auth0_client_id"] == loaded.sources["ca_bundle"] == "unset"


def test_builtin_profiles_match_the_deployments(tmp_path: Path) -> None:
    production = BUILTIN_PROFILES["production"]
    production_env = _read_env(KUSTOMIZE / "config" / "compose-api-rke" / "api.env")
    assert production["api_base_url"] == ServerMode.PROD
    assert production["auth0_domain"] == production_env["AUTH0_DOMAIN"]
    assert production["auth0_audience"] == production_env["AUTH0_AUDIENCE"]

    local = BUILTIN_PROFILES["local"]
    local_env = _read_env(KUSTOMIZE / "overlays" / "compose-api-local" / "auth0.env")
    ingress = yaml.safe_load((KUSTOMIZE / "overlays" / "compose-api-local" / "ingress.yaml").read_text())
    assert local["api_base_url"] == f"https://{ingress['spec']['rules'][0]['host']}"
    assert local["auth0_domain"] == local_env["AUTH0_DOMAIN"]
    assert local["auth0_audience"] == local_env["AUTH0_AUDIENCE"]

    for name in BUILTIN_PROFILES:  # the defaults are already canonical, so loading changes nothing
        assert _load(tmp_path, profile=name).settings.api_base_url == BUILTIN_PROFILES[name]["api_base_url"]


@pytest.mark.parametrize(
    ("flag", "env", "expected"),
    [
        (None, None, ("production", "default")),
        (None, "local", ("local", "env COMPOSE_API_CLI_PROFILE")),
        ("local", "production", ("local", "--profile")),
        ("production", "local", ("production", "--profile")),
        (None, "", ("production", "default")),  # an empty variable counts as unset
    ],
)
def test_profile_selection_precedence(
    tmp_path: Path, flag: str | None, env: str | None, expected: tuple[str, str]
) -> None:
    environ = {} if env is None else {"COMPOSE_API_CLI_PROFILE": env}
    loaded = _load(tmp_path, env=environ, profile=flag)
    assert (loaded.settings.profile, loaded.sources["profile"]) == expected


def test_environment_beats_file_beats_default(tmp_path: Path) -> None:
    config = f"""
[profiles.production]
api_base_url = "https://file.example.org"
auth0_client_id = "{CLIENT_ID}"
callback_port = 8401
"""
    env = {"COMPOSE_API_CLI_API_BASE_URL": "https://env.example.org", "COMPOSE_API_CLI_CALLBACK_PORT": ""}
    loaded = _load(tmp_path, config, env=env)
    settings, sources = loaded.settings, loaded.sources
    assert (settings.api_base_url, sources["api_base_url"]) == (
        "https://env.example.org",
        "env COMPOSE_API_CLI_API_BASE_URL",
    )
    assert (settings.auth0_client_id, sources["auth0_client_id"]) == (CLIENT_ID, "file [profiles.production]")
    assert (settings.callback_port, sources["callback_port"]) == (8401, "file [profiles.production]")
    assert (settings.auth0_audience, sources["auth0_audience"]) == (
        BUILTIN_PROFILES["production"]["auth0_audience"],
        "default",
    )
    assert loaded.config_found is True


def test_custom_profile_is_defined_by_the_file(tmp_path: Path) -> None:
    config = f"""
[profiles.dev]
api_base_url = "http://localhost:8000"
auth0_domain = "dev-tenant.us.auth0.com"
auth0_audience = "https://api.compose.local"
auth0_client_id = "{CLIENT_ID}"
database_connection = "Username-Password-Authentication"
google_connection = "google-oauth2"
"""
    settings = _load(tmp_path, config, profile="dev").settings
    assert settings.api_base_url == "http://localhost:8000"
    assert settings.google_connection == "google-oauth2"
    assert settings.callback_port == DEFAULT_CALLBACK_PORT


def test_custom_profile_must_set_what_has_no_default(tmp_path: Path) -> None:
    message = _config_error(tmp_path, '[profiles.dev]\napi_base_url = "https://compose.example.org"\n', profile="dev")
    assert "auth0_domain is not set for profile 'dev'" in message
    assert "auth0_audience is not set for profile 'dev'" in message
    assert "COMPOSE_API_CLI_AUTH0_DOMAIN" in message


def test_unknown_profile_is_not_invented(tmp_path: Path) -> None:
    message = _config_error(tmp_path, profile="prodution")
    assert "'prodution'" in message and "is not built in" in message


@pytest.mark.parametrize("name", ["", "-x", "a b", "x" * 65, "../etc", "prod\x1b[31m"])
def test_invalid_profile_name(tmp_path: Path, name: str) -> None:
    message = _config_error(tmp_path, profile=name)
    assert message.startswith("profile (--profile) must be")


@pytest.mark.parametrize(
    ("config", "env", "fragment"),
    [
        (None, {"COMPOSE_API_CLI_AUTH0_CLIENT_SECRET": LEAK_CANARY}, "looks like a secret"),
        (None, {"COMPOSE_API_CLI_ACCESS_TOKEN": LEAK_CANARY}, "looks like a secret"),
        (None, {"COMPOSE_API_CLI_PASSWORD": LEAK_CANARY}, "looks like a secret"),
        (None, {"COMPOSE_API_CLI_TIMEOUT": "5"}, "unknown setting 'COMPOSE_API_CLI_TIMEOUT' in the environment"),
        (None, {"COMPOSE_API_CLI_api_base_url": "https://x.example.org"}, "unknown setting"),
        (f'[profiles.production]\nclient_secret = "{LEAK_CANARY}"\n', None, "looks like a secret"),
        (f'[profiles.unused]\nrefresh_token = "{LEAK_CANARY}"\n', None, "looks like a secret"),
        (f'password = "{LEAK_CANARY}"\n', None, "looks like a secret"),
        (f'[profiles.production.headers]\nAuthorization = "{LEAK_CANARY}"\n', None, "unknown setting 'headers'"),
        ('[profiles.production]\naudience = "https://x"\n', None, "unknown setting 'audience'"),
        ('[profiles.production]\nprofile = "local"\n', None, "unknown setting 'profile'"),
        ('default_profile = "local"\n', None, "unknown setting 'default_profile' at the top level"),
    ],
)
def test_unknown_and_secret_keys_are_refused(
    tmp_path: Path, config: str | None, env: dict[str, str] | None, fragment: str
) -> None:
    message = _config_error(tmp_path, config, env=env)
    assert fragment in message
    assert LEAK_CANARY not in message


@pytest.mark.parametrize(
    "url",
    [
        "http://compose.example.org",  # plain HTTP off loopback
        "http://10.0.0.5:8000",
        "ftp://compose.example.org",
        "compose.example.org",
        f"https://user:{LEAK_CANARY}@compose.example.org",
        f"https://{LEAK_CANARY}@compose.example.org",
        "https://compose.example.org/api",
        "https://compose.example.org/?",
        f"https://compose.example.org/?token={LEAK_CANARY}",
        "https://compose.example.org/#frag",
        "https://compose.example.org:0",
        "https://compose.example.org:99999",
        "https://compose.example.org:https",
        "https://compose.example.org.",
        "https://compose..example.org",
        "https://compose_api.example.org",
        "https://-compose.example.org",
        "https://127.1",
        "https://0x7f.0.0.1",
        "https://127.000.000.001",
        "https://[v1.fe]",
        "https://[fe80::1%25en0]",
        "https://compose%2eexample.org",
        "https:\\\\compose.example.org",
        "https://compöse.example.org",
        " https://compose.example.org",
        "https://compose.example.org\n",
        "https://",
        "https:compose.example.org",
    ],
)
def test_invalid_api_base_url(tmp_path: Path, url: str) -> None:
    message = _config_error(tmp_path, env={"COMPOSE_API_CLI_API_BASE_URL": url})
    assert message.startswith("invalid CLI configuration:\n  api_base_url (env COMPOSE_API_CLI_API_BASE_URL) ")
    assert url.strip() not in message and LEAK_CANARY not in message, "a configured value is never echoed"


@pytest.mark.parametrize(
    ("url", "canonical"),
    [
        ("HTTPS://Compose.Example.ORG:443/", "https://compose.example.org"),
        ("https://compose.example.org:8443", "https://compose.example.org:8443"),
        ("http://localhost:8000/", "http://localhost:8000"),
        ("http://127.0.0.1:80", "http://127.0.0.1"),
        ("http://127.0.0.2:8000", "http://127.0.0.2:8000"),
        ("http://[::1]:8000", "http://[::1]:8000"),
        ("https://[2001:DB8:0:0::1]", "https://[2001:db8::1]"),
        ("https://api.compose-api-local", "https://api.compose-api-local"),
    ],
)
def test_api_base_url_is_canonicalised(tmp_path: Path, url: str, canonical: str) -> None:
    assert _load(tmp_path, env={"COMPOSE_API_CLI_API_BASE_URL": url}).settings.api_base_url == canonical


@pytest.mark.parametrize(
    "domain",
    [
        "https://tenant.us.auth0.com",
        "tenant.us.auth0.com/",
        "tenant.us.auth0.com:443",
        "localhost",
        "10.1.2.3",
        "tenant..auth0.com",
        "tenant.us.auth0.com.",
        "tenant_x.auth0.com",
        "tenant us.auth0.com",
    ],
)
def test_invalid_auth0_domain(tmp_path: Path, domain: str) -> None:
    message = _config_error(tmp_path, env={"COMPOSE_API_CLI_AUTH0_DOMAIN": domain})
    assert "auth0_domain (env COMPOSE_API_CLI_AUTH0_DOMAIN) must" in message


def test_auth0_domain_is_lower_cased_and_the_issuer_derived(tmp_path: Path) -> None:
    settings = _load(tmp_path, env={"COMPOSE_API_CLI_AUTH0_DOMAIN": "Tenant.US.Auth0.com"}).settings
    assert settings.auth0_domain == "tenant.us.auth0.com"
    assert settings.issuer == "https://tenant.us.auth0.com/"


def test_audience_is_kept_exactly(tmp_path: Path) -> None:
    settings = _load(tmp_path, env={"COMPOSE_API_CLI_AUTH0_AUDIENCE": "https://API.compose.local/"}).settings
    assert settings.auth0_audience == "https://API.compose.local/", "an identifier is not a URL to normalise"


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("auth0_audience", "https://api.compose.local ", "must be the exact API identifier"),
        ("auth0_audience", "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl", "looks like a token"),
        ("auth0_client_id", "<published-production-native-client-id>", "public Client ID"),
        ("auth0_client_id", "abc def", "public Client ID"),
        ("database_connection", "Username Password", "Auth0 connection name"),
        ("google_connection", "-google", "Auth0 connection name"),
        ("callback_port", "80", "unprivileged port"),
        ("callback_port", "65536", "unprivileged port"),
        ("callback_port", "eighty", "valid integer"),
        ("ca_bundle", "certs/ca.pem", "absolute path"),
        ("ca_bundle", "/nonexistent/ca.pem", "existing CA certificate file"),
    ],
)
def test_invalid_values_name_the_field_and_source(tmp_path: Path, field: str, value: str, fragment: str) -> None:
    variable = f"COMPOSE_API_CLI_{field.upper()}"
    message = _config_error(tmp_path, env={variable: value})
    assert f"{field} (env {variable})" in message and fragment in message
    if field != "callback_port":
        assert value not in message


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    env = {"COMPOSE_API_CLI_API_BASE_URL": "http://compose.example.org", "COMPOSE_API_CLI_CALLBACK_PORT": "1"}
    message = _config_error(tmp_path, env=env)
    assert "api_base_url" in message and "callback_port" in message


def test_file_values_must_have_the_right_type(tmp_path: Path) -> None:
    message = _config_error(tmp_path, "[profiles.production]\napi_base_url = 443\ncallback_port = '8400x'\n")
    assert "api_base_url (file [profiles.production]) Input should be a valid string" in message
    assert "callback_port (file [profiles.production])" in message


def test_ca_bundle_accepts_an_absolute_or_home_relative_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = tmp_path / "ca.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----\n")
    assert _load(tmp_path, env={"COMPOSE_API_CLI_CA_BUNDLE": str(bundle)}).settings.ca_bundle == bundle
    monkeypatch.setenv("HOME", str(tmp_path))
    assert _load(tmp_path, env={"COMPOSE_API_CLI_CA_BUNDLE": "~/ca.pem"}).settings.ca_bundle == bundle
    message = _config_error(tmp_path, env={"COMPOSE_API_CLI_CA_BUNDLE": str(tmp_path)})
    assert "existing CA certificate file" in message


@pytest.mark.parametrize(
    ("contents", "fragment"),
    [
        (b"[profiles.production\n", "is not valid TOML"),
        (b"\xff\xfe[profiles]\n", "is not UTF-8 text"),
        (b"profiles = 3\n", "must be a table of [profiles.<name>] tables"),
        (b'[profiles]\nproduction = "x"\n', "profiles.production in"),
        (b'[profiles."bad name"]\n', "table name"),
        (b"# padding\n" * 7000, "is larger than"),
    ],
)
def test_malformed_config_file(tmp_path: Path, contents: bytes, fragment: str) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(contents)
    path.chmod(0o600)
    with pytest.raises(ConfigError, match=None) as caught:
        load_cli_settings(None, environ={}, config_path=path)
    assert fragment in caught.value.message


def test_config_path_must_be_a_file(tmp_path: Path) -> None:
    (tmp_path / "config.toml").mkdir()
    assert "is not a regular file" in _config_error(tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
@pytest.mark.parametrize("mode", [0o620, 0o602, 0o666])
def test_config_file_others_can_change_is_refused(tmp_path: Path, mode: int) -> None:
    write_cli_config(tmp_path / "config.toml", "", mode=mode)
    with pytest.raises(ConfigError, match="must not be writable by group or others"):
        load_cli_settings(None, environ={}, config_path=tmp_path / "config.toml")


def test_working_directory_config_is_never_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_cli_config(tmp_path / "config.toml", '[profiles.production]\napi_base_url = "https://evil.example"\n')
    monkeypatch.chdir(tmp_path)
    loaded = load_cli_settings(None, environ={}, config_path=tmp_path / "elsewhere" / "config.toml")
    assert loaded.settings.api_base_url == BUILTIN_PROFILES["production"]["api_base_url"]


def test_missing_public_client_id_blocks_sign_in_only(tmp_path: Path) -> None:
    settings = _load(tmp_path).settings
    with pytest.raises(ConfigError, match="auth0_client_id is not set for profile 'production'") as caught:
        settings.require_client_id()
    assert "COMPOSE_API_CLI_AUTH0_CLIENT_ID" in caught.value.message
    with pytest.raises(ConfigError):
        settings.binding_key(persistent=True)


def test_requested_scopes_are_fixed_policy() -> None:
    assert requested_scopes(persistent=False) == ("openid", "profile", "email")
    assert requested_scopes(persistent=True) == ("openid", "profile", "email", OFFLINE_ACCESS_SCOPE)


@pytest.mark.parametrize(
    "change",
    [
        {"api_base_url": "https://other.example.org"},
        {"api_base_url": "https://compose.example.org:8443"},
        {"api_base_url": "http://localhost:8000"},
        {"auth0_domain": "other-tenant.example.auth0.com"},
        {"auth0_audience": "https://api.compose.example.org/"},
        {"auth0_client_id": "ZyXwVu9876543210ZyXwVu9876543210"},
    ],
)
def test_a_different_origin_never_shares_a_session(change: dict[str, str]) -> None:
    base = _settings()
    for persistent in (True, False):
        assert base.binding_key(persistent=persistent) != _settings(**change).binding_key(persistent=persistent)


@pytest.mark.parametrize(
    "change",
    [
        {"profile": "renamed"},
        {"api_base_url": "HTTPS://Compose.Example.org:443/"},
        {"auth0_domain": "TENANT.example.auth0.com"},
        {"callback_port": 8401},
        {"google_connection": "google-oauth2"},
    ],
)
def test_the_same_origin_shares_a_session(change: dict[str, Any]) -> None:
    assert _settings().binding_key(persistent=True) == _settings(**change).binding_key(persistent=True)


def test_binding_key_separates_persistent_and_ephemeral_sessions_and_reveals_nothing() -> None:
    settings = _settings()
    persistent, ephemeral = settings.binding_key(persistent=True), settings.binding_key(persistent=False)
    assert persistent != ephemeral
    assert len(persistent) == 64 and set(persistent) <= set("0123456789abcdef")
    assert CLIENT_ID not in persistent


def test_public_view_lists_exactly_the_profile_settings(tmp_path: Path) -> None:
    view = _load(tmp_path, f'[profiles.production]\nauth0_client_id = "{CLIENT_ID}"\n').public_view()
    assert view.keys() == {"profile", "config_file", "settings", "derived"}
    assert tuple(view["settings"]) == PROFILE_FIELDS
    assert view["settings"]["auth0_client_id"] == {"value": CLIENT_ID, "source": "file [profiles.production]"}
    assert view["derived"] == {
        "issuer": f"https://{BUILTIN_PROFILES['production']['auth0_domain']}/",
        "redirect_uri": "http://127.0.0.1:8400/callback",
    }
