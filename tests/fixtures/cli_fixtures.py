"""CLI test support: an isolated home, a guard against network and browser use, and a fake Auth0 tenant.

The CLI reads `COMPOSE_API_CLI_*` variables and a config file in the platform's user config directory, so every
fixture here clears the first and points the second into `tmp_path`: a developer's real profile never leaks into a test.

`FakeTenant` serves discovery, JWKS, token, device and revocation endpoints over `httpx.MockTransport`, signing real
RS256 tokens with `FakeAuth0`'s keys -- the same test vectors the API's own verifier is tested with. `FakeBrowser`
plays the person at Auth0's hosted page and follows the redirect to the CLI's real loopback listener.
"""

import base64
import hashlib
import os
import socket
import sys
import threading
import webbrowser
from collections.abc import Generator
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
import platformdirs
import pytest

from compose_api.cli.config import ENV_PREFIX, CliSettings, default_config_path
from tests.fixtures.auth_fixtures import AUTH0_TEST_AUDIENCE, AUTH0_TEST_DOMAIN, AUTH0_TEST_ISSUER, FakeAuth0

CLI_CLIENT_ID = "CliNativeClient0123456789abcdefAB"
DATABASE_CONNECTION = "Username-Password-Authentication"
GOOGLE_CONNECTION = "google-oauth2"
# Distinctive values, so any appearance in output, logs or a repr is easy to find.
REFRESH_TOKEN = "rt-LEAK-CANARY-8d3f"  # noqa: S105 -- a canary, not a credential
CODE_PREFIX = "code-LEAK-CANARY-"
DEVICE_CODE = "dc-LEAK-CANARY-51ab"
USER_CODE = "WDJB-MJHT"
DESCRIPTION_CANARY = "description-LEAK-CANARY-c0de"


def write_cli_config(path: Path, text: str, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    return path


@pytest.fixture
def cli_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The config file the CLI will read by default, inside `tmp_path` and not yet created."""
    for name in list(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name)
    home = tmp_path / "home"
    home.mkdir()
    # The environment isolates child processes on POSIX; Windows resolves its folders through the shell API instead,
    # so in-process the lookup itself is redirected too.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    config_dir = home / ".config" / "compose-api"
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda *_args, **_kwargs: str(config_dir))
    path = default_config_path()
    if not path.is_relative_to(home):
        pytest.fail(f"the CLI's config path escaped the test's home on {sys.platform}; isolate it another way")
    return path


@pytest.fixture
def cli_subprocess_env(cli_config_path: Path) -> dict[str, str]:
    """The whole environment for a CLI child process: the private home and nothing else, so no server settings."""
    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT") if name in os.environ}
    env.update(HOME=os.environ["HOME"], XDG_CONFIG_HOME=os.environ["XDG_CONFIG_HOME"])
    return env


@pytest.fixture
def no_network_or_browser(monkeypatch: pytest.MonkeyPatch) -> Generator[list[str]]:
    """Fail the test if the CLI opens a browser, connects a socket or binds a listener."""
    attempts: list[str] = []

    def refuse(name: str) -> object:
        def refused(*_args: object, **_kwargs: object) -> NoReturn:
            attempts.append(name)
            raise AssertionError(f"the CLI called {name}")

        return refused

    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, name, refuse(f"webbrowser.{name}"))
    for name in ("connect", "connect_ex", "bind"):
        monkeypatch.setattr(socket.socket, name, refuse(f"socket.{name}"))
    yield attempts
    assert attempts == [], f"the CLI reached for the network or a browser: {attempts}"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def cli_settings(**overrides: Any) -> CliSettings:
    """A complete profile pointing at the fake tenant, on a callback port nothing else is using."""
    values: dict[str, Any] = {
        "profile": "test",
        "api_base_url": "https://api.compose.test",
        "auth0_domain": AUTH0_TEST_DOMAIN,
        "auth0_audience": AUTH0_TEST_AUDIENCE,
        "auth0_client_id": CLI_CLIENT_ID,
        "database_connection": DATABASE_CONNECTION,
        "google_connection": GOOGLE_CONNECTION,
    }
    if "callback_port" not in overrides:
        values["callback_port"] = free_port()
    return CliSettings(**{**values, **overrides})


class FakeTenant:
    """An Auth0 tenant for the CLI behind httpx.MockTransport.

    Queue a response on an endpoint to answer the next POST there; otherwise the token endpoint redeems codes issued
    by `authorize`, checking the PKCE verifier, redirect URI and client exactly as Auth0 would.
    """

    TOKEN = "/oauth/token"  # noqa: S105 -- an endpoint path
    DEVICE = "/oauth/device/code"
    REVOKE = "/oauth/revoke"

    def __init__(self, auth0: FakeAuth0) -> None:
        self.auth0 = auth0
        self.subject = "auth0|cli-user"
        self.discovery: dict[str, Any] = {
            "issuer": AUTH0_TEST_ISSUER,
            "authorization_endpoint": f"{AUTH0_TEST_ISSUER}authorize",
            "token_endpoint": f"{AUTH0_TEST_ISSUER}oauth/token",
            "device_authorization_endpoint": f"{AUTH0_TEST_ISSUER}oauth/device/code",
            "revocation_endpoint": f"{AUTH0_TEST_ISSUER}oauth/revoke",
            "jwks_uri": f"{AUTH0_TEST_ISSUER}.well-known/jwks.json",
            "code_challenge_methods_supported": ["S256", "plain"],
            "id_token_signing_alg_values_supported": ["HS256", "RS256"],
        }
        self.requests: list[httpx.Request] = []
        self.posts: list[tuple[str, dict[str, str]]] = []
        self.authorize_requests: list[dict[str, str]] = []
        self.issued: list[dict[str, Any]] = []  # every token body handed out, for leak scans
        self.discovery_available = True
        self.queued: dict[str, list[httpx.Response]] = {self.TOKEN: [], self.DEVICE: [], self.REVOKE: []}
        self._codes: dict[str, dict[str, str]] = {}

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def queue(self, path: str, *responses: httpx.Response | dict[str, Any]) -> None:
        for response in responses:
            self.queued[path].append(
                response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)
            )

    def forms(self, path: str) -> list[dict[str, str]]:
        return [form for posted, form in self.posts if posted == path]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.url.host != AUTH0_TEST_DOMAIN:
            return httpx.Response(404)
        if request.method == "GET" and path == "/.well-known/openid-configuration":
            return httpx.Response(200, json=self.discovery) if self.discovery_available else httpx.Response(503)
        if request.method == "GET" and path == "/.well-known/jwks.json":
            return self.auth0.handle_jwks(request)
        if request.method == "POST" and path in self.queued:
            form = dict(parse_qsl(request.content.decode()))
            self.posts.append((path, form))
            if self.queued[path]:
                return self.queued[path].pop(0)
            if path == self.TOKEN and form.get("grant_type") == "authorization_code":
                return self._redeem(form)
            return httpx.Response(500)
        return httpx.Response(404)

    def token_response(
        self,
        *,
        nonce: str | None = None,
        subject: str | None = None,
        scope: str | None = "openid profile email offline_access",
        refresh_token: str | None = REFRESH_TOKEN,
        expires_in: Any = 300,
        access: dict[str, Any] | None = None,
        id_token: dict[str, Any] | None = None,
        include_id_token: bool = True,
    ) -> dict[str, Any]:
        """A token endpoint body with real signed tokens. `access`/`id_token` override claims (None omits one)."""
        subject = subject or self.subject
        body: dict[str, Any] = {
            "access_token": self.auth0.token(**{"sub": subject, **(access or {})}),
            "token_type": "Bearer",
            "expires_in": expires_in,
        }
        if scope is not None:
            body["scope"] = scope
        if refresh_token is not None:
            body["refresh_token"] = refresh_token
        if include_id_token:
            body["id_token"] = self.id_token(**{"nonce": nonce, "sub": subject, **(id_token or {})})
        self.issued.append(body)
        return body

    def id_token(self, **claims: Any) -> str:
        return self.auth0.token(**{"aud": CLI_CLIENT_ID, "scope": None, **claims})

    def device_response(self, **overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "device_code": DEVICE_CODE,
            "user_code": USER_CODE,
            "verification_uri": f"{AUTH0_TEST_ISSUER}activate",
            "verification_uri_complete": f"{AUTH0_TEST_ISSUER}activate?user_code={USER_CODE}",
            "expires_in": 900,
            "interval": 5,
        }
        body.update(overrides)
        return {name: value for name, value in body.items() if value is not None}

    def authorize(self, url: str) -> str:
        """Play Auth0's /authorize for a person who signs in: a one-use code bound to this request's PKCE challenge."""
        parts = urlsplit(url)
        assert (parts.scheme, parts.netloc, parts.path) == ("https", AUTH0_TEST_DOMAIN, "/authorize")
        params = dict(parse_qsl(parts.query))
        self.authorize_requests.append(params)
        code = f"{CODE_PREFIX}{len(self._codes)}"
        self._codes[code] = params
        return code

    def _redeem(self, form: dict[str, str]) -> httpx.Response:
        params = self._codes.pop(form.get("code", ""), None)
        if params is None:
            return httpx.Response(403, json={"error": "invalid_grant", "error_description": DESCRIPTION_CANARY})
        # PKCE checked independently of the library the CLI uses to make the challenge.
        digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        if (challenge, form.get("redirect_uri"), form.get("client_id")) != (
            params["code_challenge"],
            params["redirect_uri"],
            params["client_id"],
        ):
            return httpx.Response(403, json={"error": "invalid_grant"})
        return httpx.Response(200, json=self.token_response(nonce=params["nonce"]))


class FakeBrowser:
    """The system browser plus a person at Auth0's hosted page.

    `outcome` is what the person does: "approve" signs in, "deny" refuses, "ignore" never comes back. The redirect
    goes to the CLI's real loopback listener. Called from the CLI's launcher thread, so the request is synchronous.
    """

    def __init__(self, tenant: FakeTenant, *, outcome: str = "approve", opens: bool = True) -> None:
        self.tenant = tenant
        self.outcome = outcome
        self.opens = opens
        self.urls: list[str] = []
        self.responses: list[httpx.Response] = []

    def __call__(self, url: str) -> bool:
        self.urls.append(url)
        if not self.opens:
            return False
        if self.outcome != "ignore":
            self.visit(self.redirect_for(url))
        return True

    def redirect_for(self, url: str) -> str:
        params = dict(parse_qsl(urlsplit(url).query))
        if self.outcome == "deny":
            query = {"error": "access_denied", "error_description": DESCRIPTION_CANARY, "state": params["state"]}
        else:
            query = {"code": self.tenant.authorize(url), "state": params["state"]}
        return f"{params['redirect_uri']}?{urlencode(query)}"

    def visit(self, url: str) -> None:
        with httpx.Client(trust_env=False, timeout=10) as client:
            self.responses.append(client.get(url))

    def visit_later(self, url: str) -> None:
        """Follow a link printed by --no-browser, from another thread as a person would."""
        threading.Thread(target=self.visit, args=(self.redirect_for(url),), daemon=True).start()


@pytest.fixture
def fake_tenant(fake_auth0: FakeAuth0) -> FakeTenant:
    return FakeTenant(fake_auth0)
