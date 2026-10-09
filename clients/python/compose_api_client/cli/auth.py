"""BioSimulations portal entry and separate native-client PKCE authorization.

The website does not return CLI credentials. Only Compose /auth/me can confirm
an access token before persistence. Refresh rotation is serialized and fails closed after interruption.
"""

import hashlib
import io
import json
import os
import socket
import stat
import time
import uuid
import webbrowser
from collections.abc import Callable, Generator, Iterator, Mapping
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import MappingProxyType
from urllib.parse import parse_qs, urlsplit

import httpx
import requests
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from requests_oauth2client import BearerToken, OAuth2Client

# The BioSim tenant: the issuer compose-api verifies (kustomize/config/compose-api-rke/api.env, AUTH0_DOMAIN).
ISSUER_URL = "https://dev-bu7yo7484tyxu6a1.us.auth0.com"
PORTAL_URL = "https://biosim.biosimulations.org/login"

SIGNUP_URL = PORTAL_URL  # compatibility for callers of the initial configuration module
CALLBACK_PORT = 8400
CALLBACK_PATH = "/callback"
LOGIN_TIMEOUT_SECONDS = 180
LOCK_TIMEOUT_SECONDS = 35
MAX_STORE_BYTES = 1024 * 1024
HTTP_OPTIONS = {"timeout": 10, "allow_redirects": False}
TOKEN_FILE = Path.home() / ".compose-api" / "tokens.json"


class Environment(BaseModel):
    """One deployment's public Auth0 native application. Neither value is a secret."""

    model_config = ConfigDict(frozen=True)

    client_id: StrictStr
    audience: StrictStr


# Keyed by the CLI's --url, so a token issued for one deployment is never sent to another. Client IDs are the
# auth0-pulumi compose-api stack's `cli_profiles` export; audiences are the AUTH0_AUDIENCE each deployment verifies.
ENVIRONMENTS: Mapping[str, Environment] = MappingProxyType({
    "https://compose.cam.uchc.edu": Environment(
        client_id="1FV43fysEjhTrYYRNaMEGvCteu4g2ay4", audience="https://api.compose.cam.uchc.edu"
    ),
    "https://api.compose-api-local": Environment(
        client_id="Fp3QmULWNIhdutlBRVFm2HjPGapqdnKV", audience="https://api.compose.local"
    ),
})


def environment_for(url: str) -> Environment | None:
    """The Auth0 application for ``url``, or None when that URL has none (use --token there)."""
    return ENVIRONMENTS.get(url.rstrip("/"))


class LoginError(Exception):
    """A safe, fixed diagnostic; never include provider responses or credentials."""


class StoredToken(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    access_token: StrictStr = Field(min_length=1, repr=False)
    expires_at: float = Field(gt=0, allow_inf_nan=False)
    refresh_token: StrictStr | None = Field(default=None, min_length=1, repr=False)
    refresh_pending: bool = False
    subject: StrictStr | None = None
    generation: str = Field(default_factory=lambda: uuid.uuid4().hex)


def open_browser(url: str, notify: Callable[[str], None]) -> None:
    """Always provide a manual URL, including on headless machines."""
    notify(f"Open in your browser: {url}")
    try:
        opened = webbrowser.open(url, new=1, autoraise=True)
    except (webbrowser.Error, OSError):
        opened = False
    if not opened:
        notify("Could not open a browser automatically. Open the URL above manually.")


def _read_callback_headers(connection: socket.socket, deadline: float) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or len(data) >= 16384:
            return b""
        connection.settimeout(min(remaining, 1))
        chunk = connection.recv(min(4096, 16384 - len(data)))
        if not chunk:
            return b""
        data.extend(chunk)
    return bytes(data)


def _interactive_tokens(env: Environment, notify: Callable[[str], None]) -> StoredToken:
    """Run only after the user returns from the portal. No website tokens are consumed."""
    callback: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def handle(self) -> None:
            # Read at most one bounded header block under the *overall* deadline.
            # A read timeout alone can be defeated by a peer sending one byte at a time.
            try:
                data = _read_callback_headers(self.request, deadline)
                if data:
                    self.rfile.close()
                    self.rfile = io.BytesIO(data)
                    self.handle_one_request()
            except OSError:
                return

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query, keep_blank_values=True)
            valid = (
                not parsed.scheme
                and not parsed.netloc
                and not parsed.fragment
                and self.headers.get("Host") == f"127.0.0.1:{server.server_address[1]}"
                and parsed.path == CALLBACK_PATH
                and len(query.get("state", [])) == 1
                and bool(query["state"][0])
                and (
                    (len(query.get("code", [])) == 1 and bool(query["code"][0]) and "error" not in query)
                    or (len(query.get("error", [])) == 1 and bool(query["error"][0]) and "code" not in query)
                )
            )
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if valid:
                callback.append(self.path)
            self.wfile.write(b"Return to the terminal. Authentication is not confirmed yet.")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # callback contains an authorization code; never log it

    with requests.Session() as session, HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler) as server:
        # Bound both the overall wait and an incomplete local HTTP request.
        server.socket.settimeout(1)
        callback_port = server.server_address[1]
        redirect = f"http://127.0.0.1:{callback_port}{CALLBACK_PATH}"
        client = oauth2_client(env, session, redirect)
        request = client.authorization_request(scope="openid email profile offline_access", audience=env.audience)
        deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
        open_browser(str(request.uri), notify)
        while not callback:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("CLI authorization timed out; run compose-api auth login again.")
            server.timeout = min(remaining, 1)
            server.handle_request()
        response = request.validate_callback(f"http://127.0.0.1:{callback_port}{callback[0]}")
        token = client.authorization_code(
            response, validate=False, requests_kwargs={"timeout": 10, "allow_redirects": False}
        )
        return _tokens(token)


def login_interactive_tokens(env: Environment, notify: Callable[[str], None]) -> StoredToken:
    try:
        return _interactive_tokens(env, notify)
    except (LoginError, TimeoutError):
        raise
    except Exception:
        raise LoginError("CLI authorization failed or was cancelled. No credentials were saved.") from None


def get_endpoints(session: requests.Session) -> dict[str, str]:
    """The tenant's OAuth endpoints from discovery, accepted only when they are exactly the configured issuer's and
    it supports S256 PKCE. Never follows a redirect, so discovery cannot move credentials to another host."""
    response = session.get(f"{ISSUER_URL}/.well-known/openid-configuration", timeout=10, allow_redirects=False)
    response.raise_for_status()
    d = response.json()
    expected = {
        "issuer": f"{ISSUER_URL}/",
        "authorization_endpoint": f"{ISSUER_URL}/authorize",
        "token_endpoint": f"{ISSUER_URL}/oauth/token",
        "revocation_endpoint": f"{ISSUER_URL}/oauth/revoke",
    }
    if (
        not isinstance(d, dict)
        or any(d.get(key) != value for key, value in expected.items())
        or "S256" not in d.get("code_challenge_methods_supported", [])
    ):
        raise LoginError("Auth0 discovery does not match the configured issuer and PKCE endpoints.")
    return expected


def oauth2_client(env: Environment, session: requests.Session, redirect: str | None = None) -> OAuth2Client:
    endpoints = get_endpoints(session)
    return OAuth2Client(
        token_endpoint=endpoints["token_endpoint"],
        authorization_endpoint=endpoints["authorization_endpoint"],
        revocation_endpoint=endpoints["revocation_endpoint"],
        client_id=env.client_id,
        redirect_uri=redirect,
        session=session,
    )


def _tokens(token: BearerToken) -> StoredToken:
    # ID tokens are deliberately discarded. The API, not the ID token, confirms authorization.
    if not token.expires_at or token.expires_at.timestamp() <= time.time() + 30:
        raise LoginError("Auth0 returned no usable, unexpired access token.")
    return StoredToken(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_at=token.expires_at.timestamp(),
    )


def _check_file(fd: int) -> None:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise LoginError("Credential files must be private, owned by you, mode 0600, and not linked.")


def _directory() -> int:
    if os.name != "posix":
        raise LoginError("Secure file storage is supported on POSIX only; use --token on this system.")
    TOKEN_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(TOKEN_FILE.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(fd)
        raise LoginError("Credential directory must be owned by you with mode 0700 and must not be a symlink.")
    return fd


@contextmanager
def _locked() -> Iterator[int]:
    # Imported only after checking the platform; never silently fall back to unlocked storage.
    directory = _directory()
    import fcntl

    try:
        lock = os.open("tokens.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
        try:
            _check_file(lock)
            deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LoginError("Credential store is busy; retry after the other command finishes.") from None
                    time.sleep(0.05)
            yield directory
        finally:
            os.close(lock)  # releases flock even on cancellation or failure
    finally:
        os.close(directory)


def _read_tokens(directory: int) -> dict[str, StoredToken]:
    try:
        fd = os.open(TOKEN_FILE.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return {}
    with os.fdopen(fd) as file:
        _check_file(file.fileno())
        raw = file.read(MAX_STORE_BYTES + 1)
        if len(raw) > MAX_STORE_BYTES:
            raise LoginError("Credential file exceeds the supported size.")
        try:
            document = json.loads(raw)
        except (TypeError, ValueError):
            raise LoginError("Credential file is corrupt; run compose-api auth logout, then auth login.") from None
        if not isinstance(document, dict):
            raise LoginError("Credential file is corrupt; run compose-api auth logout, then auth login.")
        records = {}
        for key, value in document.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise LoginError("Credential file is corrupt; run compose-api auth logout, then auth login.")
            if "generation" not in value:
                legacy_token = value.get("access_token")
                if not isinstance(legacy_token, str):
                    raise LoginError("Credential file is corrupt; run compose-api auth logout, then auth login.")
                # Legacy access-only records predate generations; derive a stable identity for each token.
                value["generation"] = hashlib.sha256(legacy_token.encode()).hexdigest()
            try:
                records[key] = StoredToken.model_validate(value)
            except ValueError:
                raise LoginError("Credential file is corrupt; run compose-api auth logout, then auth login.") from None
        return records


def _write_tokens(directory: int, records: dict[str, StoredToken]) -> None:
    name = f".tokens-{uuid.uuid4().hex}.tmp"
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump({key: value.model_dump() for key, value in records.items()}, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, TOKEN_FILE.name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(name, dir_fd=directory)


def save(url: str, token: StoredToken | None) -> None:
    """Persist a verified login, or clear it, under the same lock used by refresh/logout."""
    if environment_for(url) is None:
        raise LoginError("No Auth0 application for this URL; use --token.")
    with _locked() as directory:
        records = _read_tokens(directory)
        key = url.rstrip("/")
        if token is None:
            records.pop(key, None)
        else:
            records[key] = token
        _write_tokens(directory, records)


def confirm_token(url: str, token: StoredToken) -> str:
    from compose_api_client.ext import ComposeSession

    env = environment_for(url)
    if env is None:
        raise LoginError("No Auth0 application for this URL; use --token.")
    with ComposeSession(url, token=token.access_token, timeout=10) as session:
        identity = session.whoami()
    if identity.issuer != f"{ISSUER_URL}/" or env.audience not in identity.audience:
        raise LoginError("The API reported an incompatible issuer or audience.")
    return identity.subject


def _refresh(url: str, saved: StoredToken) -> StoredToken:
    env = environment_for(url)
    if env is None or not saved.refresh_token:
        raise LoginError("Stored login expired; run compose-api auth login or auth logout.")
    with requests.Session() as session:
        token = oauth2_client(env, session).refresh_token(saved.refresh_token, requests_kwargs=HTTP_OPTIONS)
    fresh = _tokens(token)
    if not fresh.refresh_token or fresh.refresh_token == saved.refresh_token:
        raise LoginError("Auth0 did not rotate the refresh token; run compose-api auth login.")
    fresh.generation = saved.generation
    fresh.subject = confirm_token(url, fresh)
    if saved.subject is not None and fresh.subject != saved.subject:
        raise LoginError("Refreshed credentials changed identity; run compose-api auth login.")
    return fresh


def access_token(url: str, *, generation: str | None = None) -> str | None:
    """Resolve each request under a process lock; never replay an ambiguously consumed refresh token."""
    if environment_for(url) is None:
        return None
    # lexists detects a dangling symlink as an error rather than treating it as an anonymous session.
    if not os.path.lexists(TOKEN_FILE.parent):
        if generation is not None:
            raise LoginError("Stored session was removed; run compose-api auth login.")
        return None
    try:
        with _locked() as directory:
            return _access_token_locked(url, directory, generation)
    except LoginError:
        raise
    except Exception:
        raise LoginError(
            "Cannot use secure credentials; run auth login or check storage permissions and format."
        ) from None


def _access_token_locked(url: str, directory: int, generation: str | None) -> str | None:
    records = _read_tokens(directory)
    key = url.rstrip("/")
    saved = records.get(key)
    if generation is not None and (saved is None or saved.generation != generation):
        raise LoginError("Stored session changed or was logged out; restart the command after login.")
    if saved is None:
        return None
    if saved.refresh_pending:
        raise LoginError("A previous refresh was interrupted; run compose-api auth login or auth logout.")
    if saved.expires_at > time.time() + 30:
        return saved.access_token
    if not saved.refresh_token:
        raise LoginError("Stored login expired; run compose-api auth login or auth logout.")
    # Durable write-ahead marker: death, timeout, cancellation, API failure or a failed final write
    # must NEVER cause the old refresh token to be replayed. Keep it only for best-effort revocation.
    records[key] = saved.model_copy(update={"refresh_pending": True})
    _write_tokens(directory, records)
    fresh = _refresh(url, saved)
    records[key] = fresh
    _write_tokens(directory, records)
    return fresh.access_token


def logout(url: str) -> bool:
    """Clear locally first, then best-effort revoke under the lock. False means revocation unconfirmed."""
    if not os.path.lexists(TOKEN_FILE.parent):
        return True
    with _locked() as directory:
        try:
            records = _read_tokens(directory)
        except LoginError:
            # The file cannot be safely attributed to one URL. Remove the unreadable local store so
            # the user has a recovery path, but do not attempt provider revocation without a trusted token.
            with suppress(FileNotFoundError):
                os.unlink(TOKEN_FILE.name, dir_fd=directory)
            os.fsync(directory)
            return False
        saved = records.pop(url.rstrip("/"), None)
        _write_tokens(directory, records)
        return _revoke(url, saved)


def _revoke(url: str, saved: StoredToken | None) -> bool:
    env = environment_for(url)
    if not saved or not saved.refresh_token:
        return True
    if env is None:
        return False
    try:
        with requests.Session() as session:
            return oauth2_client(env, session).revoke_refresh_token(saved.refresh_token, requests_kwargs=HTTP_OPTIONS)
    except Exception:
        return False


class StoredAuth(httpx.Auth):
    """Refresh before every API request; never replay a request or switch accounts mid-command."""

    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        try:
            with _locked() as directory:
                saved = _read_tokens(directory).get(self.url)
        except LoginError:
            raise
        except Exception:
            raise LoginError("Cannot use secure credentials; check storage permissions and format.") from None
        if saved is None:
            raise LoginError("Stored session was removed; run compose-api auth login.")
        self.generation = saved.generation

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        target = httpx.URL(self.url)
        if (request.url.scheme, request.url.host, request.url.port) != (target.scheme, target.host, target.port):
            raise LoginError("Refusing to send stored credentials outside their configured API.")
        token = access_token(self.url, generation=self.generation)
        if token is None:
            raise LoginError("Stored session was removed; run compose-api auth login.")
        request.headers["Authorization"] = f"Bearer {token}"
        yield request
