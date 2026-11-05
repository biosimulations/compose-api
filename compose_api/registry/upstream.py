"""Whether a commit is one a flagged registry entry may move to (docs/plan-entry-updates.md, E3): on its repository's
default branch (`updates: main`), or one a release tag points at (`updates: tags`). Asked of GitHub's API, anonymously
unless GITHUB_TOKEN is set, as `registry/catalog.py` does; only an environment administrator's request asks."""

import os
import re
from typing import Literal

import httpx
from pydantic import BaseModel, TypeAdapter

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^https://github\.com/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$")
_API = "https://api.github.com"

Updates = Literal["main", "tags"]


class CommitRefusedError(ValueError):
    """The commit is not one the entry may move to, or does not exist."""


class UpstreamUnavailableError(RuntimeError):
    """GitHub could not be asked."""


class _Repository(BaseModel):
    default_branch: str


class _Comparison(BaseModel):
    status: str  # how the commit stands to the base: identical, behind (an ancestor), ahead, diverged


class _Commit(BaseModel):
    sha: str


class _Tag(BaseModel):
    name: str
    commit: _Commit


_TAGS = TypeAdapter(list[_Tag])


def repository_of(git_url: str) -> str:
    """``owner/name`` of a GitHub repository URL; only GitHub repositories can be followed."""
    match = _REPOSITORY.match(git_url)
    if match is None:
        raise CommitRefusedError(f"{git_url} is not a GitHub repository, so its commits cannot be checked")
    return f"{match['owner']}/{match['name']}"


def _client() -> httpx.AsyncClient:
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    return httpx.AsyncClient(base_url=_API, headers=headers, timeout=20, follow_redirects=True)


async def _get(client: httpx.AsyncClient, path: str) -> httpx.Response | None:
    """The answer, or None for a 404 (or GitHub's 422 for a commit it cannot compare)."""
    try:
        response = await client.get(path)
    except httpx.HTTPError as e:
        raise UpstreamUnavailableError(f"GitHub could not be asked: {e}") from e
    if response.status_code in (404, 422):
        return None
    if response.status_code != 200:
        raise UpstreamUnavailableError(f"GitHub answered {response.status_code} for {path}")
    return response


async def allowed_commit(git_url: str, ref: str, updates: Updates, client: httpx.AsyncClient | None = None) -> str:
    """The full commit ``ref`` names, if the entry may move to it: a 40-character commit on the default branch (or
    a tag's, for `tags`), or a name standing for one, the default branch's head for `main`, a tag for `tags`. A
    branch is never recorded, only the commit it is at now."""
    repository = repository_of(git_url)
    async with client or _client() as http:
        if updates == "tags":
            return await _tagged(http, repository, ref)
        return await _on_default_branch(http, repository, ref)


async def _on_default_branch(http: httpx.AsyncClient, repository: str, ref: str) -> str:
    found = await _get(http, f"/repos/{repository}")
    if found is None:
        raise CommitRefusedError(f"no repository {repository} on GitHub")
    branch = _Repository.model_validate_json(found.content).default_branch
    if not _COMMIT.match(ref):
        if ref not in (branch, "HEAD"):
            raise CommitRefusedError(
                f"{ref!r}: give a full 40-character commit, or {branch!r} for the head of {repository}'s default branch"
            )
        head = await _get(http, f"/repos/{repository}/commits/{branch}")
        if head is None:
            raise CommitRefusedError(f"{repository} has no branch {branch!r}")
        sha = _Commit.model_validate_json(head.content).sha
        if not _COMMIT.match(sha):
            raise UpstreamUnavailableError(f"GitHub gave no commit for {repository}@{branch}")
        return sha
    compared = await _get(http, f"/repos/{repository}/compare/{branch}...{ref}")
    if compared is None:
        raise CommitRefusedError(f"{repository} has no commit {ref}")
    status = _Comparison.model_validate_json(compared.content).status
    if status not in ("identical", "behind"):
        raise CommitRefusedError(f"{ref} is not on {repository}'s default branch {branch!r} ({status})")
    return ref


async def _tagged(http: httpx.AsyncClient, repository: str, ref: str) -> str:
    found = await _get(http, f"/repos/{repository}/tags?per_page=100")
    if found is None:
        raise CommitRefusedError(f"no repository {repository} on GitHub")
    tags = _TAGS.validate_json(found.content)
    for tag in tags:
        if ref in (tag.name, tag.commit.sha):
            return tag.commit.sha
    raise CommitRefusedError(f"{ref!r} is neither a release tag of {repository} nor the commit of one")
