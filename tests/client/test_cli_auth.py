"""The CLI's Auth0 environments: which application and audience each --url uses, and that they stay in step
with what each deployment verifies."""

import base64
import datetime
import hashlib
import json
import logging
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import requests
from compose_api_client.cli import app, auth, commands
from compose_api_client.cli.auth import ENVIRONMENTS, ISSUER_URL, SIGNUP_URL, environment_for
from compose_api_client.ext import DEFAULT_URL, ComposeSession
from requests_oauth2client import BearerToken, OAuth2Client
from typer.testing import CliRunner

from tests.client.test_cli import FakeService

KUSTOMIZE = Path(__file__).resolve().parents[2] / "kustomize"


def _env_file(path: Path) -> dict[str, str]:
    lines = [line for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]
    return dict(line.split("=", 1) for line in lines)


def test_default_url_has_an_auth0_application() -> None:
    assert environment_for(DEFAULT_URL) is ENVIRONMENTS[DEFAULT_URL]


@pytest.mark.parametrize("url", ["https://compose.cam.uchc.edu/", "https://api.compose-api-local/"])
def test_trailing_slash_selects_the_same_environment(url: str) -> None:
    assert environment_for(url) is ENVIRONMENTS[url.rstrip("/")]


@pytest.mark.parametrize(
    "url", ["https://compose.cam.uchc.edu.evil", "http://compose.cam.uchc.edu", "http://127.0.0.1:8000"]
)
def test_other_urls_have_no_application(url: str) -> None:
    assert environment_for(url) is None


@pytest.mark.parametrize(
    ("url", "env_file"),
    [
        ("https://compose.cam.uchc.edu", KUSTOMIZE / "config" / "compose-api-rke" / "api.env"),
        ("https://api.compose-api-local", KUSTOMIZE / "overlays" / "compose-api-local" / "auth0.env"),
    ],
    ids=["production", "local"],
)
def test_environment_matches_what_the_deployment_verifies(url: str, env_file: Path) -> None:
    deployed = _env_file(env_file)
    assert ENVIRONMENTS[url].audience == deployed["AUTH0_AUDIENCE"]
    assert f"https://{deployed['AUTH0_DOMAIN']}" == ISSUER_URL


def test_signup_goes_to_the_biosim_portal() -> None:
    assert SIGNUP_URL == "https://biosim.biosimulations.org/login"


def test_help_has_no_auth_profile_flags() -> None:
    result = CliRunner().invoke(app, ["--help"], terminal_width=200)
    assert result.exit_code == 0
    for removed in ("--profile", "--auth0-", "--callback-ports", "--login-deadline", "--auth-timeout"):
        assert removed not in result.stdout


def test_anonymous_cli_does_not_load_the_login_module() -> None:
    probe = "import sys, compose_api_client.cli.commands; print('compose_api_client.cli.auth' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", probe], check=True, capture_output=True, text=True)  # noqa: S603
    assert result.stdout.strip() == "False"


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def private_tokens(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging.getLogger("httpx"), "disabled", True)
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "credentials" / "tokens.json")


@pytest.fixture(autouse=True)
def no_browser_or_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test here opens a real browser or reaches beyond loopback (the PKCE callback is real loopback HTTP)."""
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def connect(self: socket.socket, address: Any) -> None:
        if self.family != socket.AF_UNIX and address[0] not in LOOPBACK:
            pytest.fail(f"network access to {address!r}")
        real_connect(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host not in LOOPBACK:
            pytest.fail(f"DNS lookup of {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    def browser(url: str, **kwargs: Any) -> bool:
        pytest.fail(f"a real browser was asked to open {url}")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(webbrowser, "open", browser)


def test_the_network_guard_is_active() -> None:
    with pytest.raises(pytest.fail.Exception, match="DNS lookup"):
        httpx.get("https://compose.cam.uchc.edu/health")
    with pytest.raises(pytest.fail.Exception, match="real browser"):
        webbrowser.open(auth.PORTAL_URL)


@pytest.mark.parametrize("command", ["login", "signup"])
@pytest.mark.parametrize("browser", [True, False, "error"])
def test_portal_entry_and_cancellation(monkeypatch: pytest.MonkeyPatch, command: str, browser: bool | str) -> None:
    opened: list[str] = []

    def launch(url: str, **kwargs: Any) -> bool:
        opened.append(url)
        if browser == "error":
            raise webbrowser.Error("private provider error")
        return bool(browser)

    monkeypatch.setattr(webbrowser, "open", launch)
    result = CliRunner().invoke(app, ["auth", command], input="n\n")
    assert result.exit_code == (130 if command == "login" else 0)
    assert ("Login cancelled. No new credentials were saved." in result.output) is (command == "login")
    assert opened == [auth.PORTAL_URL]
    assert auth.PORTAL_URL in result.output
    assert "private provider error" not in result.output
    assert not auth.TOKEN_FILE.exists()
    if browser is not True:
        assert "manually" in result.output


ENDPOINTS = {
    "issuer": f"{ISSUER_URL}/",
    "authorization_endpoint": f"{ISSUER_URL}/authorize",
    "token_endpoint": f"{ISSUER_URL}/oauth/token",
    "revocation_endpoint": f"{ISSUER_URL}/oauth/revoke",
}


def _b64(data: dict[str, Any] | bytes) -> str:
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# An OIDC ID token as Auth0 returns one beside the access token; it must never be stored or sent to the API.
ID_TOKEN = ".".join([_b64({"alg": "RS256", "typ": "JWT"}), _b64({"sub": "auth0|id-token-user"}), _b64(b"sig")])


@pytest.fixture
def oauth_browser(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    config: dict[str, Any] = {"callback": "valid", "exchanges": [], "opened": []}
    config["exchange_method"] = OAuth2Client.authorization_code
    threads: list[threading.Thread] = []
    # Real PKCE request, state validation and loopback HTTP; only provider I/O is mocked.
    monkeypatch.setattr(auth, "CALLBACK_PORT", 0)
    monkeypatch.setattr(auth, "LOGIN_TIMEOUT_SECONDS", 0.3)
    # Discovery is the get_endpoints seam; test_discovery_* run the real one through mocked HTTP.
    config["real_get_endpoints"] = auth.get_endpoints
    monkeypatch.setattr(auth, "get_endpoints", lambda session: dict(ENDPOINTS))

    def launch(url: str, **kwargs: Any) -> bool:
        config["opened"].append(url)
        if url == auth.PORTAL_URL:
            return True
        query = parse_qs(urlsplit(url).query)
        config["query"] = query
        if config["callback"] == "timeout":
            return True
        if config["callback"] == "cancel":
            raise KeyboardInterrupt  # Ctrl-C while the CLI waits for the authorization callback
        state = query["state"][0] if config["callback"] != "state" else "wrong"
        params = {"state": state, "code": "authorization-code"}
        if config["callback"] == "denied":
            params = {"state": state, "error": "access_denied", "error_description": "sensitive"}
        if config["callback"] == "path":
            query["redirect_uri"][0] = query["redirect_uri"][0].replace("/callback", "/other")

        def send() -> None:
            with httpx.Client(trust_env=False) as client:
                client.get(query["redirect_uri"][0], params=params)

        thread = threading.Thread(target=send)
        threads.append(thread)
        thread.start()
        return bool(config["callback"] != "nobrowser")

    def exchange(self: OAuth2Client, code: Any, **kwargs: Any) -> BearerToken:
        config["exchanges"].append(code)
        assert code.code_verifier
        return BearerToken(
            "access-secret",
            refresh_token="initial-refresh",  # noqa: S106
            id_token=ID_TOKEN,
            expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
        )

    monkeypatch.setattr(webbrowser, "open", launch)
    monkeypatch.setattr(OAuth2Client, "authorization_code", exchange)
    yield config
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()


def api_session(monkeypatch: pytest.MonkeyPatch, status: int = 200, stored: list[bool] | None = None) -> list[str]:
    """Answer /auth/me with ``status`` (0: the API is unreachable); ``stored`` records whether a token file existed
    at each API call."""
    headers: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers.get("Authorization", ""))
        if stored is not None:
            stored.append(auth.TOKEN_FILE.exists())
        if status == 0:
            raise httpx.ConnectError("private connection detail", request=request)
        return httpx.Response(
            status,
            json={
                "issuer": f"{ISSUER_URL}/",
                "subject": "auth0|portal-user",
                "audience": [ENVIRONMENTS[DEFAULT_URL].audience],
                "roles": ["user"],
                "scopes": [],
                "permissions": [],
            },
        )

    def session(url: str, **kwargs: Any) -> ComposeSession:
        return ComposeSession(url, transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(commands, "ComposeSession", session)
    monkeypatch.setattr("compose_api_client.ext.ComposeSession", session)
    return headers


def test_login_pkce_verifies_before_private_storage(
    monkeypatch: pytest.MonkeyPatch, oauth_browser: dict[str, Any]
) -> None:
    stored: list[bool] = []
    headers = api_session(monkeypatch, stored=stored)
    result = CliRunner().invoke(app, ["auth", "login"], input="y\n")
    assert result.exit_code == 0, result.output
    assert headers == ["Bearer access-secret"]
    assert stored == [False]  # nothing was written until the API had confirmed the access token
    assert ID_TOKEN not in auth.TOKEN_FILE.read_text()
    assert json.loads(auth.TOKEN_FILE.read_text())[DEFAULT_URL]["subject"] == "auth0|portal-user"
    assert oauth_browser["opened"][0] == auth.PORTAL_URL
    query = oauth_browser["query"]
    assert query["audience"] == [ENVIRONMENTS[DEFAULT_URL].audience]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] and query["state"]
    assert "screen_hint" not in query
    assert "offline_access" in query["scope"][0]
    assert auth.access_token(DEFAULT_URL) == "access-secret"
    assert auth.access_token("https://other.example") is None
    assert auth.TOKEN_FILE.stat().st_mode & 0o777 == 0o600
    assert auth.TOKEN_FILE.parent.stat().st_mode & 0o777 == 0o700
    assert "access-secret" not in result.output
    assert "initial-refresh" not in result.output
    assert json.loads(auth.TOKEN_FILE.read_text())[DEFAULT_URL]["refresh_token"] == "initial-refresh"  # noqa: S105
    assert set(json.loads(auth.TOKEN_FILE.read_text())[DEFAULT_URL]) == {
        "access_token",
        "expires_at",
        "refresh_token",
        "refresh_pending",
        "generation",
        "subject",
    }


FAILED_AUTHORIZATION = "CLI authorization failed or was cancelled. No credentials were saved."
TIMED_OUT = "CLI authorization timed out. No new credentials were saved"


@pytest.mark.parametrize(
    ("callback", "exit_code", "message"),
    [
        ("state", 3, FAILED_AUTHORIZATION),
        ("denied", 3, FAILED_AUTHORIZATION),
        ("timeout", 5, TIMED_OUT),
        ("path", 5, TIMED_OUT),
        ("cancel", 130, "Login cancelled. No new credentials were saved."),
    ],
)
def test_bad_callback_never_exchanges_or_saves(
    oauth_browser: dict[str, Any], callback: str, exit_code: int, message: str
) -> None:
    oauth_browser["callback"] = callback
    result = CliRunner().invoke(app, ["auth", "login"], input="y\n")
    assert result.exit_code == exit_code, result.output
    assert message in result.output
    assert not auth.TOKEN_FILE.exists()
    assert oauth_browser["exchanges"] == []
    assert "sensitive" not in result.output and "access_denied" not in result.output
    assert "Authenticated" not in result.output


def test_browser_failure_prints_the_authorization_url(
    monkeypatch: pytest.MonkeyPatch, oauth_browser: dict[str, Any]
) -> None:
    oauth_browser["callback"] = "nobrowser"
    api_session(monkeypatch)
    result = CliRunner().invoke(app, ["auth", "login"], input="y\n")
    assert result.exit_code == 0, result.output
    authorize = oauth_browser["opened"][1]
    assert authorize.startswith(f"{ISSUER_URL}/authorize?")
    assert f"Open in your browser: {authorize}" in result.output
    assert "Open the URL above manually" in result.output


@pytest.mark.parametrize("status", [401, 404, 500, 0], ids=["rejected", "no-route", "error", "unreachable"])
def test_unverified_access_token_is_not_saved(
    monkeypatch: pytest.MonkeyPatch,
    oauth_browser: dict[str, Any],
    status: int,
) -> None:
    api_session(monkeypatch, status)
    result = CliRunner().invoke(app, ["--verbose", "auth", "login"], input="y\n")
    assert result.exit_code == 3
    assert not auth.TOKEN_FILE.exists()
    assert "Authenticated:" not in result.output
    assert "access-secret" not in result.output
    assert "private connection detail" not in result.output


def test_storage_expiry_precedence_and_logout(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.save(
        DEFAULT_URL,
        auth.StoredToken(access_token="expired", expires_at=time.time() - 1),  # noqa: S106
    )
    with pytest.raises(auth.LoginError, match="expired"):
        auth.access_token(DEFAULT_URL)
    headers = api_session(monkeypatch)
    result = CliRunner().invoke(app, ["--token", "explicit", "auth", "whoami"])
    assert result.exit_code == 0
    assert headers == ["Bearer explicit"]
    result = CliRunner().invoke(app, ["auth", "logout"])
    assert result.exit_code == 0
    assert auth.access_token(DEFAULT_URL) is None


def test_storage_refuses_insecure_directory_and_symlink(tmp_path: Path) -> None:
    auth.TOKEN_FILE.parent.mkdir(mode=0o755)
    with pytest.raises(auth.LoginError, match="0700"):
        auth.save(
            DEFAULT_URL,
            auth.StoredToken(access_token="secret", expires_at=time.time() + 3600),  # noqa: S106
        )
    auth.TOKEN_FILE.parent.chmod(0o700)
    target = tmp_path / "target"
    target.write_text("untouched")
    auth.TOKEN_FILE.symlink_to(target)
    with pytest.raises(OSError):
        auth.save(DEFAULT_URL, None)
    assert target.read_text() == "untouched"


def test_unknown_environment_login() -> None:
    result = CliRunner().invoke(app, ["--url", "https://other.example", "auth", "login"])
    assert result.exit_code == 2


def test_signup_never_calls_provider_or_api(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    def launch(url: str, **kwargs: Any) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(webbrowser, "open", launch)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("signup must not make an HTTP request")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    result = CliRunner().invoke(app, ["auth", "signup"])
    assert result.exit_code == 0
    assert opened == ["https://biosim.biosimulations.org/login"]
    assert "Sign Up" in result.output and "compose-api auth login" in result.output
    assert "No CLI credentials" in result.output
    assert "Authenticated" not in result.output
    assert not auth.TOKEN_FILE.exists()


def test_existing_session_is_confirmed_without_new_authorization(
    monkeypatch: pytest.MonkeyPatch,
    oauth_browser: dict[str, Any],
) -> None:
    auth.save(DEFAULT_URL, auth.StoredToken(access_token="stored", expires_at=time.time() + 3600))  # noqa: S106
    headers = api_session(monkeypatch)
    result = CliRunner().invoke(app, ["auth", "login"])
    assert result.exit_code == 0
    assert headers == ["Bearer stored"]
    assert oauth_browser["opened"] == [auth.PORTAL_URL]
    assert oauth_browser["exchanges"] == []


@pytest.mark.parametrize("failure", ["issuer", "network", "exchange", "expired"])
def test_provider_failures_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
    oauth_browser: dict[str, Any],
    failure: str,
) -> None:
    def broken_get(*args: Any, **kwargs: Any) -> requests.Response:
        if failure == "network":
            raise requests.ConnectionError("sensitive")
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"issuer":"https://untrusted.example/"}'
        return response

    def broken_exchange(*args: Any, **kwargs: Any) -> BearerToken:
        if failure == "exchange":
            raise RuntimeError("sensitive")
        return BearerToken("sensitive", expires_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=60))

    if failure in {"issuer", "network"}:
        monkeypatch.setattr(auth, "get_endpoints", oauth_browser["real_get_endpoints"])
        monkeypatch.setattr(requests.Session, "get", broken_get)
    else:
        monkeypatch.setattr(OAuth2Client, "authorization_code", broken_exchange)
    result = CliRunner().invoke(app, ["--verbose", "auth", "login"], input="y\n")
    assert result.exit_code == 3
    assert "sensitive" not in result.output
    assert not auth.TOKEN_FILE.exists()


def test_stored_credentials_are_used_only_for_bound_api(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.save(DEFAULT_URL, auth.StoredToken(access_token="stored", expires_at=time.time() + 3600))  # noqa: S106
    headers = api_session(monkeypatch)
    with commands.make_session(commands.Settings()) as session:
        session.whoami()
    with commands.make_session(commands.Settings(url="https://unrelated.example")) as session:
        session.whoami()
    assert headers == ["Bearer stored", ""]


def test_token_exchange_uses_pkce_without_client_secret(
    monkeypatch: pytest.MonkeyPatch,
    oauth_browser: dict[str, Any],
) -> None:
    api_session(monkeypatch)
    monkeypatch.setattr(OAuth2Client, "authorization_code", oauth_browser["exchange_method"])

    def send(self: requests.Session, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        assert request.url == f"{ISSUER_URL}/oauth/token"
        assert request.method == "POST"
        assert "Authorization" not in request.headers
        assert isinstance(request.body, str)
        body = parse_qs(request.body)
        assert "client_secret" not in body
        assert body["client_id"] == [ENVIRONMENTS[DEFAULT_URL].client_id]
        assert body["grant_type"] == ["authorization_code"]
        assert body["code"] == ["authorization-code"]
        assert body["redirect_uri"] == oauth_browser["query"]["redirect_uri"]
        digest = hashlib.sha256(body["code_verifier"][0].encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        assert [challenge] == oauth_browser["query"]["code_challenge"]
        assert kwargs["timeout"] == 10
        assert kwargs["allow_redirects"] is False
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"access_token":"access-secret","token_type":"Bearer","expires_in":3600}'
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    result = CliRunner().invoke(app, ["auth", "login"], input="y\n")
    assert result.exit_code == 0, result.output
    assert auth.access_token(DEFAULT_URL) == "access-secret"


def refreshable() -> auth.StoredToken:
    return auth.StoredToken(
        access_token="old-access",  # noqa: S106
        refresh_token="old-refresh",  # noqa: S106
        expires_at=time.time() - 1,
    )


def test_refresh_rotates_verifies_and_persists(monkeypatch: pytest.MonkeyPatch, oauth_browser: dict[str, Any]) -> None:
    saved = refreshable()
    auth.save(DEFAULT_URL, saved)
    confirmed: list[str] = []
    monkeypatch.setattr(auth, "confirm_token", lambda url, token: confirmed.append(token.access_token))
    exchanges: list[str] = []

    def refresh(self: OAuth2Client, token: str, **kwargs: Any) -> BearerToken:
        exchanges.append(token)
        assert json.loads(auth.TOKEN_FILE.read_text())[DEFAULT_URL]["refresh_pending"] is True
        assert kwargs["requests_kwargs"] == {"timeout": 10, "allow_redirects": False}
        return BearerToken("fresh-access", refresh_token="fresh-refresh", expires_in=3600)  # noqa: S106

    monkeypatch.setattr(OAuth2Client, "refresh_token", refresh)
    assert auth.access_token(DEFAULT_URL) == "fresh-access"
    assert auth.access_token(DEFAULT_URL) == "fresh-access"
    assert exchanges == ["old-refresh"]
    assert confirmed == ["fresh-access"]
    record = json.loads(auth.TOKEN_FILE.read_text())[DEFAULT_URL]
    assert record["refresh_token"] == "fresh-refresh"  # noqa: S105
    assert record["generation"] == saved.generation
    assert record["refresh_pending"] is False


@pytest.mark.parametrize("failure", ["network", "api", "rotation", "save", "cancel"])
def test_ambiguous_refresh_never_replays(
    monkeypatch: pytest.MonkeyPatch,
    oauth_browser: dict[str, Any],
    failure: str,
) -> None:
    auth.save(DEFAULT_URL, refreshable())
    calls: list[str] = []

    def refresh(self: OAuth2Client, token: str, **kwargs: Any) -> BearerToken:
        calls.append(token)
        if failure == "network":
            raise requests.Timeout("secret response")
        if failure == "cancel":
            raise KeyboardInterrupt
        rotated = "old-refresh" if failure == "rotation" else "fresh-refresh"
        return BearerToken("fresh-access", refresh_token=rotated, expires_in=3600)

    def confirm(url: str, token: auth.StoredToken) -> None:
        if failure == "api":
            raise RuntimeError("private API failure")

    original_write = auth._write_tokens
    writes: list[int] = []

    def write(directory: int, records: dict[str, auth.StoredToken]) -> None:
        writes.append(directory)
        if failure == "save" and len(writes) == 2:
            raise OSError("disk full")
        original_write(directory, records)

    monkeypatch.setattr(OAuth2Client, "refresh_token", refresh)
    monkeypatch.setattr(auth, "confirm_token", confirm)
    monkeypatch.setattr(auth, "_write_tokens", write)
    error = KeyboardInterrupt if failure == "cancel" else auth.LoginError
    with pytest.raises(error):
        auth.access_token(DEFAULT_URL)
    with pytest.raises(auth.LoginError, match="interrupted"):
        auth.access_token(DEFAULT_URL)
    assert calls == ["old-refresh"]


def test_refresh_marker_failure_never_calls_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.save(DEFAULT_URL, refreshable())

    def fail(*args: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(auth, "_write_tokens", fail)
    monkeypatch.setattr(auth, "_refresh", lambda *args: pytest.fail("must persist marker first"))
    with pytest.raises(auth.LoginError):
        auth.access_token(DEFAULT_URL)


def test_refresh_is_serialized_between_processes(tmp_path: Path) -> None:
    auth.save(DEFAULT_URL, refreshable())
    count = tmp_path / "calls"
    code = """
import sys, time
from pathlib import Path
from compose_api_client.cli import auth
from compose_api_client.ext import DEFAULT_URL
auth.TOKEN_FILE = Path(sys.argv[1])
def refresh(url, saved):
    with Path(sys.argv[2]).open("a") as file:
        file.write("refresh\\n")
    time.sleep(0.2)
    return auth.StoredToken(access_token="fresh", refresh_token="rotated", expires_at=time.time()+3600,
                            generation=saved.generation)
auth._refresh = refresh
assert auth.access_token(DEFAULT_URL) == "fresh"
"""
    processes = [
        subprocess.Popen(  # noqa: S603 - fixed test script, no provider I/O
            [sys.executable, "-c", code, str(auth.TOKEN_FILE), str(count)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(4)
    ]
    for process in processes:
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr.decode()
    assert count.read_text().splitlines() == ["refresh"]


def test_process_death_keeps_refresh_invalidated() -> None:
    auth.save(DEFAULT_URL, refreshable())
    code = """
import os, sys
from pathlib import Path
from compose_api_client.cli import auth
from compose_api_client.ext import DEFAULT_URL
auth.TOKEN_FILE = Path(sys.argv[1])
auth._refresh = lambda *args: os._exit(17)
auth.access_token(DEFAULT_URL)
"""
    result = subprocess.run([sys.executable, "-c", code, str(auth.TOKEN_FILE)], check=False)  # noqa: S603
    assert result.returncode == 17
    with pytest.raises(auth.LoginError, match="interrupted"):
        auth.access_token(DEFAULT_URL)


@pytest.mark.parametrize("succeed", [True, False])
def test_logout_clears_before_revocation(
    monkeypatch: pytest.MonkeyPatch,
    oauth_browser: dict[str, Any],
    succeed: bool,
) -> None:
    auth.save(DEFAULT_URL, refreshable())

    def revoke(self: OAuth2Client, token: str, **kwargs: Any) -> bool:
        assert DEFAULT_URL not in json.loads(auth.TOKEN_FILE.read_text())
        assert token == "old-refresh"  # noqa: S105
        if not succeed:
            raise requests.Timeout("private error")
        return True

    monkeypatch.setattr(OAuth2Client, "revoke_refresh_token", revoke)
    assert auth.logout(DEFAULT_URL) is succeed
    assert auth.access_token(DEFAULT_URL) is None


def test_long_running_session_refreshes_and_stops_after_logout(monkeypatch: pytest.MonkeyPatch) -> None:
    token = refreshable().model_copy(update={"expires_at": time.time() + 3600})
    auth.save(DEFAULT_URL, token)
    headers = api_session(monkeypatch)

    def refresh(url: str, saved: auth.StoredToken) -> auth.StoredToken:
        return saved.model_copy(
            update={"access_token": "fresh", "refresh_token": "rotated", "expires_at": time.time() + 3600}
        )

    monkeypatch.setattr(auth, "_refresh", refresh)
    monkeypatch.setattr(auth, "_revoke", lambda *args: True)
    with commands.make_session(commands.Settings()) as session:
        session.whoami()
        auth.save(DEFAULT_URL, token.model_copy(update={"expires_at": time.time() - 1}))
        session.whoami()
        auth.logout(DEFAULT_URL)
        with pytest.raises(auth.LoginError, match="logged out"):
            session.whoami()
    assert headers == ["Bearer old-access", "Bearer fresh"]


def test_existing_command_does_not_switch_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.save(DEFAULT_URL, refreshable().model_copy(update={"expires_at": time.time() + 3600}))
    headers = api_session(monkeypatch)
    with commands.make_session(commands.Settings()) as session:
        auth.save(DEFAULT_URL, auth.StoredToken(access_token="new-user", expires_at=time.time() + 3600))  # noqa: S106
        with pytest.raises(auth.LoginError, match="changed"):
            session.whoami()
    assert headers == []  # refused before sending, and never retried with the other account


@pytest.mark.parametrize("target", ["directory", "file", "lock"])
def test_symlinks_never_become_anonymous(tmp_path: Path, target: str) -> None:
    if target == "directory":
        auth.TOKEN_FILE.parent.symlink_to(tmp_path / "missing", target_is_directory=True)
    else:
        auth.TOKEN_FILE.parent.mkdir(mode=0o700)
        path = auth.TOKEN_FILE if target == "file" else auth.TOKEN_FILE.parent / "tokens.lock"
        path.symlink_to(tmp_path / "missing")
    with pytest.raises(auth.LoginError):
        auth.access_token(DEFAULT_URL)


def test_legacy_access_only_record_is_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.TOKEN_FILE.parent.mkdir(mode=0o700)
    auth.TOKEN_FILE.write_text(json.dumps({DEFAULT_URL: {"access_token": "legacy", "expires_at": time.time() + 3600}}))
    auth.TOKEN_FILE.chmod(0o600)
    headers = api_session(monkeypatch)
    with commands.make_session(commands.Settings()) as session:
        session.whoami()
        session.whoami()
    assert headers == ["Bearer legacy", "Bearer legacy"]


def test_logout_waits_for_rotation_and_revokes_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.save(DEFAULT_URL, refreshable())
    refreshing = threading.Event()
    release = threading.Event()
    logged_out = threading.Event()
    revoked: list[str | None] = []
    errors: list[BaseException] = []

    def refresh(url: str, saved: auth.StoredToken) -> auth.StoredToken:
        refreshing.set()
        assert release.wait(3)
        return saved.model_copy(
            update={"refresh_token": "rotated", "access_token": "fresh", "expires_at": time.time() + 3600}
        )

    def revoke(url: str, saved: auth.StoredToken | None) -> bool:
        revoked.append(saved.refresh_token if saved else None)
        return True

    def run_refresh() -> None:
        try:
            auth.access_token(DEFAULT_URL)
        except BaseException as exc:
            errors.append(exc)

    def run_logout() -> None:
        try:
            auth.logout(DEFAULT_URL)
        except BaseException as exc:
            errors.append(exc)
        finally:
            logged_out.set()

    monkeypatch.setattr(auth, "_refresh", refresh)
    monkeypatch.setattr(auth, "_revoke", revoke)
    first = threading.Thread(target=run_refresh)
    second = threading.Thread(target=run_logout)
    first.start()
    assert refreshing.wait(3)
    second.start()
    try:
        assert not logged_out.wait(0.1)
    finally:
        release.set()
        first.join(3)
        second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert revoked == ["rotated"]
    assert auth.access_token(DEFAULT_URL) is None


@pytest.mark.parametrize("corruption", ["json", "mode", "hardlink", "foreign", "nan"])
def test_corrupt_storage_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, corruption: str) -> None:
    auth.save(DEFAULT_URL, refreshable())
    if corruption == "json":
        auth.TOKEN_FILE.write_text("not-json")
    elif corruption == "mode":
        auth.TOKEN_FILE.chmod(0o644)
    elif corruption == "hardlink":
        (tmp_path / "linked-token").hardlink_to(auth.TOKEN_FILE)
    elif corruption == "foreign":
        import os

        monkeypatch.setattr(os, "getuid", lambda: auth.TOKEN_FILE.stat().st_uid + 1)
    else:
        record = json.loads(auth.TOKEN_FILE.read_text())
        record[DEFAULT_URL]["expires_at"] = float("nan")
        auth.TOKEN_FILE.write_text(json.dumps(record))
    with pytest.raises(auth.LoginError):
        auth.access_token(DEFAULT_URL)


def test_logout_recovers_from_corrupt_store() -> None:
    auth.TOKEN_FILE.parent.mkdir(mode=0o700)
    auth.TOKEN_FILE.write_text("not-json")
    auth.TOKEN_FILE.chmod(0o600)
    assert auth.logout(DEFAULT_URL) is False
    assert not auth.TOKEN_FILE.exists()


@pytest.mark.parametrize("record", [{"expires_at": time.time() + 3600}, {"access_token": 42}])
def test_logout_recovers_from_malformed_legacy_record(record: dict[str, Any]) -> None:
    auth.TOKEN_FILE.parent.mkdir(mode=0o700)
    auth.TOKEN_FILE.write_text(json.dumps({DEFAULT_URL: record}))
    auth.TOKEN_FILE.chmod(0o600)
    assert auth.logout(DEFAULT_URL) is False
    assert not auth.TOKEN_FILE.exists()


def test_storage_fails_safely_on_unsupported_os(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.setattr(os, "name", "nt")
    with pytest.raises(auth.LoginError, match="POSIX"):
        auth.save(DEFAULT_URL, refreshable())


def test_lock_timeout_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "LOCK_TIMEOUT_SECONDS", 0.1)
    auth.save(DEFAULT_URL, refreshable())
    with auth._locked(), pytest.raises(auth.LoginError, match="busy"):
        auth.access_token(DEFAULT_URL)


def test_slow_callback_cannot_extend_overall_deadline() -> None:
    receiver, sender = socket.socketpair()

    def send() -> None:
        try:
            for _ in range(100):
                sender.sendall(b"x")
                time.sleep(0.01)
        except OSError:
            pass
        finally:
            sender.close()

    thread = threading.Thread(target=send)
    thread.start()
    start = time.monotonic()
    try:
        with suppress(TimeoutError):
            assert auth._read_callback_headers(receiver, start + 0.15) == b""
        assert time.monotonic() - start < 0.6
    finally:
        receiver.close()
        thread.join(2)
    assert not thread.is_alive()


def test_refresh_rejects_changed_identity(monkeypatch: pytest.MonkeyPatch, oauth_browser: dict[str, Any]) -> None:
    saved = refreshable().model_copy(update={"subject": "original-user"})
    auth.save(DEFAULT_URL, saved)
    monkeypatch.setattr(auth, "confirm_token", lambda *args: "different-user")
    monkeypatch.setattr(
        OAuth2Client,
        "refresh_token",
        lambda *args, **kwargs: BearerToken(
            "fresh",
            refresh_token="rotated",  # noqa: S106
            expires_in=3600,
        ),
    )
    with pytest.raises(auth.LoginError, match="changed identity"):
        auth.access_token(DEFAULT_URL)
    with pytest.raises(auth.LoginError, match="interrupted"):
        auth.access_token(DEFAULT_URL)


def test_revoke_request_is_public_client_and_body_only(
    monkeypatch: pytest.MonkeyPatch,
    oauth_browser: dict[str, Any],
) -> None:
    auth.save(DEFAULT_URL, refreshable())
    calls: list[str] = []

    def send(self: requests.Session, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        assert request.url == f"{ISSUER_URL}/oauth/revoke"
        assert request.method == "POST"
        assert "Authorization" not in request.headers
        assert isinstance(request.body, str)
        body = parse_qs(request.body)
        assert body["token"] == ["old-refresh"]
        assert body["token_type_hint"] == ["refresh_token"]
        assert body["client_id"] == [ENVIRONMENTS[DEFAULT_URL].client_id]
        assert "client_secret" not in body
        calls.append(request.url)
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    assert auth.logout(DEFAULT_URL)
    assert calls == [f"{ISSUER_URL}/oauth/revoke"]


def test_refresh_wire_request_and_api_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    oauth_browser: dict[str, Any],
) -> None:
    auth.save(DEFAULT_URL, refreshable().model_copy(update={"subject": "auth0|portal-user"}))
    headers = api_session(monkeypatch)
    calls: list[str] = []

    def send(self: requests.Session, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        assert request.url == f"{ISSUER_URL}/oauth/token"
        assert request.method == "POST"
        assert "Authorization" not in request.headers
        assert isinstance(request.body, str)
        body = parse_qs(request.body)
        assert body["grant_type"] == ["refresh_token"]
        assert body["refresh_token"] == ["old-refresh"]
        assert body["client_id"] == [ENVIRONMENTS[DEFAULT_URL].client_id]
        assert "client_secret" not in body
        calls.append(request.url)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({
            "access_token": "fresh-access",
            "refresh_token": "rotated",
            "token_type": "Bearer",
            "expires_in": 3600,
        }).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    assert auth.access_token(DEFAULT_URL) == "fresh-access"
    assert calls == [f"{ISSUER_URL}/oauth/token"]
    assert headers == ["Bearer fresh-access"]


# -- request wiring: the acceptance matrix for make_session -------------------------------------------------------

ACCEPTANCE_COMMANDS = {
    "run": ["run", "{doc}"],
    "status": ["status", "7"],
    "wait": ["wait", "7", "--poll", "0"],
    "results": ["results", "7", "--out", "{out}"],
    "simulations list": ["simulations", "list"],
    "datasets list": ["datasets", "list"],
}


def serve(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    """The real make_session, with only the network replaced."""

    def session(url: str, **kwargs: Any) -> ComposeSession:
        return ComposeSession(url, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(commands, "ComposeSession", session)


def acceptance_argv(command: str, tmp_path: Path) -> list[str]:
    doc = tmp_path / "experiment.omex"
    doc.write_bytes(b"omex")
    return [arg.format(doc=doc, out=tmp_path) for arg in ACCEPTANCE_COMMANDS[command]]


@pytest.mark.parametrize("credentials", ["anonymous", "token", "stored"])
@pytest.mark.parametrize("command", list(ACCEPTANCE_COMMANDS))
def test_commands_work_anonymously_with_a_token_and_with_a_stored_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str, credentials: str
) -> None:
    if credentials != "anonymous":
        # Also present for --token, which must take precedence over it.
        auth.save(DEFAULT_URL, auth.StoredToken(access_token="stored", expires_at=time.time() + 3600))  # noqa: S106
    fake = FakeService()
    serve(monkeypatch, fake)
    flags = ["--token", "explicit"] if credentials == "token" else []
    result = CliRunner().invoke(app, ["--output", "json", "--quiet", *flags, *acceptance_argv(command, tmp_path)])
    assert result.exit_code == 0, result.output
    expected = {"anonymous": None, "token": "Bearer explicit", "stored": "Bearer stored"}[credentials]
    assert fake.requests
    assert {request.headers.get("Authorization") for request in fake.requests} == {expected}
    if credentials == "anonymous":
        assert not auth.TOKEN_FILE.parent.exists()


def test_stored_login_renews_before_each_request_of_a_long_running_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    auth.save(DEFAULT_URL, refreshable())
    issued: list[str] = []

    def refresh(url: str, saved: auth.StoredToken) -> auth.StoredToken:
        issued.append(f"access-{len(issued) + 1}")
        # Inside the 30 s renewal window, so the next request has to renew again.
        return saved.model_copy(
            update={
                "access_token": issued[-1],
                "refresh_token": f"refresh-{len(issued)}",
                "expires_at": time.time() + 5,
            }
        )

    monkeypatch.setattr(auth, "_refresh", refresh)
    fake = FakeService(["running", "running", "completed"])
    serve(monkeypatch, fake)
    argv = ["run", str(tmp_path / "experiment.omex"), "--wait", "--poll", "0", "--download", str(tmp_path / "out")]
    (tmp_path / "experiment.omex").write_bytes(b"omex")
    result = CliRunner().invoke(app, ["--output", "json", "--quiet", *argv])
    assert result.exit_code == 0, result.output
    sent = [request.headers["Authorization"] for request in fake.requests]
    paths = [request.url.path for request in fake.requests]
    assert paths.count("/results/simulation/status") == 3 and paths[-1] == "/results/simulation/results/file"
    assert sent == [f"Bearer {token}" for token in issued[1:]]
    assert len(set(sent)) == len(sent)


def test_logout_during_a_long_running_command_stops_it_with_the_login_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth.save(DEFAULT_URL, auth.StoredToken(access_token="stored", expires_at=time.time() + 3600))  # noqa: S106
    monkeypatch.setattr(auth, "_revoke", lambda *args: True)
    fake = FakeService(["running"])

    def handle(request: httpx.Request) -> httpx.Response:
        response = fake(request)
        if len(fake.requests) == 2:
            auth.logout(DEFAULT_URL)  # from another terminal, between two polls
        return response

    serve(monkeypatch, handle)
    result = CliRunner().invoke(app, ["--quiet", "wait", "7", "--poll", "0.01", "--wait-timeout", "5"])
    assert result.exit_code == 3
    assert "compose-api auth login" in result.stderr
    assert len(fake.requests) == 2
    assert "stored" not in result.output


@pytest.mark.parametrize("command", list(ACCEPTANCE_COMMANDS))
@pytest.mark.parametrize("breakage", ["mode", "interrupted", "expired"])
def test_a_broken_stored_login_exits_3_with_the_login_hint_and_never_goes_anonymous(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str, breakage: str
) -> None:
    saved = refreshable()
    if breakage == "interrupted":
        saved = saved.model_copy(update={"refresh_pending": True})
    if breakage == "expired":
        saved = saved.model_copy(update={"refresh_token": None})
    auth.save(DEFAULT_URL, saved)
    if breakage == "mode":
        auth.TOKEN_FILE.chmod(0o644)
    monkeypatch.setattr(auth, "_refresh", lambda *args: pytest.fail("a broken login must not refresh"))
    fake = FakeService()
    serve(monkeypatch, fake)
    result = CliRunner().invoke(app, ["--quiet", *acceptance_argv(command, tmp_path)])
    assert result.exit_code == 3, result.output
    assert "compose-api auth login" in result.stderr
    assert "auth logout" in result.stderr
    assert fake.requests == []
    assert "old-access" not in result.output and "old-refresh" not in result.output


def test_unreadable_store_while_attaching_renewal_exits_3(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.save(DEFAULT_URL, auth.StoredToken(access_token="stored", expires_at=time.time() + 3600))  # noqa: S106
    real_locked = auth._locked
    calls: list[int] = []

    def locked() -> Any:
        calls.append(1)
        if len(calls) == 2:  # the read StoredAuth makes after the first resolution
            raise PermissionError("private path detail")
        return real_locked()

    monkeypatch.setattr(auth, "_locked", locked)
    serve(monkeypatch, FakeService())
    result = CliRunner().invoke(app, ["--quiet", "status", "7"])
    assert result.exit_code == 3
    assert "private path detail" not in result.output
    assert commands.LOGIN_HINT in result.stderr


def test_empty_token_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeService()
    serve(monkeypatch, fake)
    result = CliRunner().invoke(app, ["--token", " ", "status", "7"])
    assert result.exit_code == 2
    assert fake.requests == []


@pytest.mark.parametrize(("status", "exit_code"), [(200, 0), (401, 3)])
def test_login_confirms_a_supplied_token_and_saves_nothing(
    monkeypatch: pytest.MonkeyPatch, oauth_browser: dict[str, Any], status: int, exit_code: int
) -> None:
    headers = api_session(monkeypatch, status)
    result = CliRunner().invoke(app, ["--token", "supplied", "auth", "login"])
    assert result.exit_code == exit_code, result.output
    assert headers == ["Bearer supplied"]
    assert oauth_browser["opened"] == [auth.PORTAL_URL]
    assert oauth_browser["exchanges"] == []
    assert not auth.TOKEN_FILE.exists()
    assert "supplied" not in result.output.replace("supplied token", "")
    if status == 401:
        assert "did not accept the supplied token" in result.output


def test_whoami_uses_the_stored_login(monkeypatch: pytest.MonkeyPatch) -> None:
    auth.save(DEFAULT_URL, auth.StoredToken(access_token="stored", expires_at=time.time() + 3600))  # noqa: S106
    headers = api_session(monkeypatch)
    result = CliRunner().invoke(app, ["--output", "json", "auth", "whoami"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["subject"] == "auth0|portal-user"
    assert headers == ["Bearer stored"]


# -- discovery, origin binding and the logout command --------------------------------------------------------------


def discovery_send(
    monkeypatch: pytest.MonkeyPatch, document: Any, status: int = 200, headers: dict[str, str] | None = None
) -> list[tuple[str | None, str | None, Any, Any]]:
    sent: list[tuple[str | None, str | None, Any, Any]] = []

    def send(self: requests.Session, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        sent.append((request.method, request.url, kwargs["timeout"], kwargs["allow_redirects"]))
        response = requests.Response()
        response.status_code = status
        response.headers.update(headers or {})
        response._content = json.dumps(document).encode() if document is not None else b""
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    return sent


def test_discovery_request_is_bounded_and_returns_the_issuers_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = discovery_send(monkeypatch, {**ENDPOINTS, "code_challenge_methods_supported": ["plain", "S256"]})
    with requests.Session() as session:
        assert auth.get_endpoints(session) == ENDPOINTS
    assert sent == [("GET", f"{ISSUER_URL}/.well-known/openid-configuration", 10, False)]


@pytest.mark.parametrize(
    "document",
    [
        {**ENDPOINTS, "issuer": "https://untrusted.example/", "code_challenge_methods_supported": ["S256"]},
        {
            **ENDPOINTS,
            "token_endpoint": "https://untrusted.example/token",
            "code_challenge_methods_supported": ["S256"],
        },
        {**ENDPOINTS, "code_challenge_methods_supported": ["plain"]},
        ENDPOINTS,
        [ENDPOINTS],
    ],
    ids=["issuer", "token-endpoint", "no-s256", "no-pkce-methods", "not-an-object"],
)
def test_discovery_rejects_anything_but_the_configured_issuer(monkeypatch: pytest.MonkeyPatch, document: Any) -> None:
    discovery_send(monkeypatch, document)
    with requests.Session() as session, pytest.raises(auth.LoginError, match="discovery"):
        auth.get_endpoints(session)


def test_discovery_does_not_follow_a_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = discovery_send(monkeypatch, None, 302, {"Location": "https://untrusted.example/.well-known"})
    with requests.Session() as session, pytest.raises(ValueError):  # an empty body is not a discovery document
        auth.get_endpoints(session)
    assert len(sent) == 1


@pytest.mark.parametrize(
    "target",
    [
        "https://untrusted.example/simulations",
        "http://compose.cam.uchc.edu/simulations",
        "https://compose.cam.uchc.edu:8443/",
    ],
    ids=["host", "scheme", "port"],
)
def test_stored_credentials_never_leave_their_origin(target: str) -> None:
    auth.save(DEFAULT_URL, auth.StoredToken(access_token="stored", expires_at=time.time() + 3600))  # noqa: S106
    request = httpx.Request("GET", target)
    with pytest.raises(auth.LoginError, match="Refusing"):
        next(auth.StoredAuth(DEFAULT_URL).auth_flow(request))
    assert "Authorization" not in request.headers


@pytest.mark.parametrize("revoked", [True, False], ids=["confirmed", "unconfirmed"])
def test_logout_command_removes_the_entry_before_best_effort_revocation(
    monkeypatch: pytest.MonkeyPatch, oauth_browser: dict[str, Any], revoked: bool
) -> None:
    local = "https://api.compose-api-local"
    auth.save(DEFAULT_URL, refreshable())
    auth.save(local, auth.StoredToken(access_token="local", expires_at=time.time() + 3600))  # noqa: S106
    present_at_revocation: list[bool] = []

    def revoke(self: OAuth2Client, token: str, **kwargs: Any) -> bool:
        present_at_revocation.append(DEFAULT_URL in json.loads(auth.TOKEN_FILE.read_text()))
        if not revoked:
            raise requests.ConnectionError("private provider detail")
        return True

    monkeypatch.setattr(OAuth2Client, "revoke_refresh_token", revoke)
    result = CliRunner().invoke(app, ["auth", "logout"])
    assert result.exit_code == 0, result.output
    assert present_at_revocation == [False]
    assert auth.access_token(DEFAULT_URL) is None  # not restored when revocation is unconfirmed
    assert auth.access_token(local) == "local"  # only --url's entry is removed
    assert ("could not be confirmed" in result.output) is not revoked
    assert "Browser sessions and issued access tokens may remain valid." in result.output
    assert "signed out" not in result.output.lower()
    assert "private provider detail" not in result.output and "old-refresh" not in result.output


def test_logout_without_a_stored_login_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OAuth2Client, "revoke_refresh_token", lambda *args, **kwargs: pytest.fail("nothing to revoke"))
    result = CliRunner().invoke(app, ["auth", "logout"])
    assert result.exit_code == 0
    assert not auth.TOKEN_FILE.exists()
