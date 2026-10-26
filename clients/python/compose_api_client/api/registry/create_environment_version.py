from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.environment_version import EnvironmentVersion
from ...models.new_environment_version import NewEnvironmentVersion
from ...types import Response


def _get_kwargs(
    name: str,
    *,
    body: NewEnvironmentVersion,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/registry/environments/{name}/versions".format(
            name=quote(str(name), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | EnvironmentVersion | None:
    if response.status_code == 200:
        response_200 = EnvironmentVersion.from_dict(response.json())

        return response_200

    if response.status_code == 201:
        response_201 = EnvironmentVersion.from_dict(response.json())

        return response_201

    if response.status_code == 401:
        response_401 = cast(Any, None)
        return response_401

    if response.status_code == 403:
        response_403 = cast(Any, None)
        return response_403

    if response.status_code == 404:
        response_404 = cast(Any, None)
        return response_404

    if response.status_code == 422:
        response_422 = cast(Any, None)
        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | EnvironmentVersion]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    body: NewEnvironmentVersion,
) -> Response[Any | EnvironmentVersion]:
    """Make a new version: a composed environment's entries at a date, or a prebuilt one's image by digest

     The new version is `building` until its image is built or pulled, then `ready` (or `failed`). It
    does not
    become the default: runs get it once an administrator makes it so (`PUT …/default`). A composed
    environment's
    version is `resolving` first, while its entries are locked together in a Job of their own; one that
    does not
    resolve is `failed`, with pixi's explanation in `failure` (docs/plan-environment-composition.md,
    step 4).

    Args:
        name (str):
        body (NewEnvironmentVersion): What to make a version from. A composed environment (one
            that lists its registry entries): a date to resolve
            its entries at (default now); a mash-up is an environment of its own, never a version of
            another. A prebuilt one:
            its image by digest. (Library lists, the shared uv path's `custom` versions, are retired:
            docs/plan-environment-composition.md, D8.5; versions made that way stay readable.)

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnvironmentVersion]
    """

    kwargs = _get_kwargs(
        name=name,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    body: NewEnvironmentVersion,
) -> Any | EnvironmentVersion | None:
    """Make a new version: a composed environment's entries at a date, or a prebuilt one's image by digest

     The new version is `building` until its image is built or pulled, then `ready` (or `failed`). It
    does not
    become the default: runs get it once an administrator makes it so (`PUT …/default`). A composed
    environment's
    version is `resolving` first, while its entries are locked together in a Job of their own; one that
    does not
    resolve is `failed`, with pixi's explanation in `failure` (docs/plan-environment-composition.md,
    step 4).

    Args:
        name (str):
        body (NewEnvironmentVersion): What to make a version from. A composed environment (one
            that lists its registry entries): a date to resolve
            its entries at (default now); a mash-up is an environment of its own, never a version of
            another. A prebuilt one:
            its image by digest. (Library lists, the shared uv path's `custom` versions, are retired:
            docs/plan-environment-composition.md, D8.5; versions made that way stay readable.)

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnvironmentVersion
    """

    return sync_detailed(
        name=name,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    body: NewEnvironmentVersion,
) -> Response[Any | EnvironmentVersion]:
    """Make a new version: a composed environment's entries at a date, or a prebuilt one's image by digest

     The new version is `building` until its image is built or pulled, then `ready` (or `failed`). It
    does not
    become the default: runs get it once an administrator makes it so (`PUT …/default`). A composed
    environment's
    version is `resolving` first, while its entries are locked together in a Job of their own; one that
    does not
    resolve is `failed`, with pixi's explanation in `failure` (docs/plan-environment-composition.md,
    step 4).

    Args:
        name (str):
        body (NewEnvironmentVersion): What to make a version from. A composed environment (one
            that lists its registry entries): a date to resolve
            its entries at (default now); a mash-up is an environment of its own, never a version of
            another. A prebuilt one:
            its image by digest. (Library lists, the shared uv path's `custom` versions, are retired:
            docs/plan-environment-composition.md, D8.5; versions made that way stay readable.)

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnvironmentVersion]
    """

    kwargs = _get_kwargs(
        name=name,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    body: NewEnvironmentVersion,
) -> Any | EnvironmentVersion | None:
    """Make a new version: a composed environment's entries at a date, or a prebuilt one's image by digest

     The new version is `building` until its image is built or pulled, then `ready` (or `failed`). It
    does not
    become the default: runs get it once an administrator makes it so (`PUT …/default`). A composed
    environment's
    version is `resolving` first, while its entries are locked together in a Job of their own; one that
    does not
    resolve is `failed`, with pixi's explanation in `failure` (docs/plan-environment-composition.md,
    step 4).

    Args:
        name (str):
        body (NewEnvironmentVersion): What to make a version from. A composed environment (one
            that lists its registry entries): a date to resolve
            its entries at (default now); a mash-up is an environment of its own, never a version of
            another. A prebuilt one:
            its image by digest. (Library lists, the shared uv path's `custom` versions, are retired:
            docs/plan-environment-composition.md, D8.5; versions made that way stay readable.)

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnvironmentVersion
    """

    return (
        await asyncio_detailed(
            name=name,
            client=client,
            body=body,
        )
    ).parsed
