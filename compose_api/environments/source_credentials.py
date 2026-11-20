"""Read access to private repositories, for the Jobs that fetch them (docs/plan-private-repo-usage.md, section C).

A registry entry with an ``access_role`` is a private repository. The service keeps no credential for it. A GitHub
App, installed on the repository's organization for selected repositories only, mints an installation token when a
Job needs one: read-only (``contents: read``), scoped to exactly the private repositories that version installs, and
valid for an hour. A Job receives the token in a Secret of its own (``build_k8s.credentials_secret``), never in its
spec, and git reads it through a credential helper that only answers ``get``. The token is never logged.
"""

import datetime
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt

from compose_api.config import get_settings

GITHUB_API = "https://api.github.com"
# A cached token is reused only while it outlives what it is handed to: a lock Job runs for 30 minutes at most (a
# build asks for more: build_k8s.BUILD_TOKEN_LIFETIME_SECONDS).
MIN_LIFETIME_SECONDS = 40 * 60
# What requests to GitHub go through when set: the test seam, as `authentication.JwksCache`'s `transport` is.
transport: httpx.AsyncBaseTransport | None = None


class SourceCredentialsError(Exception):
    """No token could be had for a version's private repositories: a 503, with no version recorded for it."""


@dataclass(frozen=True, order=True)
class PrivateSource:
    """A private repository a version installs: its URL as its entry gives it, and the commit it is pinned to."""

    url: str
    commit: str

    @property
    def repository(self) -> tuple[str, str]:
        """Its organization and name. `SourceCredentialsError` for anything but a repository on github.com."""
        parsed = urlparse(self.url)
        parts = parsed.path.strip("/").removesuffix(".git").split("/")
        if parsed.scheme != "https" or parsed.hostname != "github.com" or len(parts) != 2 or not all(parts):
            raise SourceCredentialsError(f"{self.url} is not a GitHub repository, the only kind fetched privately")
        return parts[0], parts[1]


def private_sources(entries: Iterable[Mapping[str, Any]]) -> tuple[PrivateSource, ...]:
    """The private repositories among a version's recorded entries (``pixi.ComposedSpec.as_json``): each entry with an
    access role that installs from git."""
    found = set()
    for entry in entries:
        install = entry.get("install") or {}
        if entry.get("access_role") and install.get("git"):
            found.add(PrivateSource(url=str(install["git"]), commit=str(install["commit"])))
    return tuple(sorted(found))


_tokens: dict[tuple[str, ...], tuple[str, float]] = {}


async def token_for(sources: Iterable[PrivateSource], min_lifetime: int = MIN_LIFETIME_SECONDS) -> str:
    """An installation token that reads ``sources`` and nothing else, minted by the GitHub App (or one minted for the
    same repositories that still has ``min_lifetime`` seconds to live). `SourceCredentialsError` when this deployment
    has no App, the repositories span organizations, or GitHub refuses."""
    repositories = sorted({source.repository for source in sources})
    key = tuple(f"{owner}/{name}" for owner, name in repositories)
    cached = _tokens.get(key)
    if cached is not None and cached[1] - time.time() > min_lifetime:
        return cached[0]
    token, expires_at = await _mint(repositories)
    _tokens[key] = (token, expires_at)
    return token


async def _mint(repositories: list[tuple[str, str]]) -> tuple[str, float]:
    owners = {owner for owner, _ in repositories}
    if len(owners) != 1:
        raise SourceCredentialsError(f"private repositories come from one organization at a time, not {sorted(owners)}")
    owner = owners.pop()
    names = [name for _, name in repositories]
    headers = {
        "Authorization": f"Bearer {_app_jwt()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(base_url=GITHUB_API, headers=headers, timeout=30, transport=transport) as client:
            installation = await client.get(f"/repos/{owner}/{names[0]}/installation")
            installation.raise_for_status()
            minted = await client.post(
                f"/app/installations/{installation.json()['id']}/access_tokens",
                json={"repositories": names, "permissions": {"contents": "read"}},
            )
            minted.raise_for_status()
            body = minted.json()
        token = str(body["token"])
        expires_at = datetime.datetime.fromisoformat(str(body["expires_at"])).timestamp()
    except httpx.HTTPError as e:  # its message names the request and the status, never a header
        raise SourceCredentialsError(f"GitHub gave no read access to {owner}/{{{','.join(names)}}}: {e}") from e
    except (KeyError, TypeError, ValueError) as e:  # an answer of another shape (never the answer itself)
        raise SourceCredentialsError(f"GitHub's answer for {owner}/{{{','.join(names)}}} was not a token") from e
    return token, expires_at


def _app_jwt() -> str:
    """The App's own credential, for the two requests that mint a token: RS256, ten minutes at most (GitHub's limit),
    issued a minute early for clock drift."""
    settings = get_settings()
    if not settings.github_app_id:
        raise SourceCredentialsError("this deployment has no GitHub App (GITHUB_APP_ID) to read private repositories")
    try:
        private_key = Path(settings.github_app_key_file).read_text()
    except OSError as e:
        raise SourceCredentialsError(f"the GitHub App's key could not be read: {type(e).__name__}") from e
    now = int(time.time())
    try:
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": settings.github_app_id}, private_key, "RS256")
    except jwt.PyJWTError as e:
        raise SourceCredentialsError(f"the GitHub App's key is not an RSA private key: {type(e).__name__}") from e
