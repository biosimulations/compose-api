from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.environment_export import EnvironmentExport
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    name: str,
    number: int,
    *,
    format_: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_format_: None | str | Unset
    if isinstance(format_, Unset):
        json_format_ = UNSET
    else:
        json_format_ = format_
    params["format"] = json_format_

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/registry/environments/{name}/versions/{number}/export".format(
            name=quote(str(name), safe=""),
            number=quote(str(number), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | EnvironmentExport | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = EnvironmentExport.from_dict(response.json())

        return response_200

    if response.status_code == 404:
        response_404 = cast(Any, None)
        return response_404

    if response.status_code == 409:
        response_409 = cast(Any, None)
        return response_409

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | EnvironmentExport | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
    format_: None | str | Unset = UNSET,
) -> Response[Any | EnvironmentExport | HTTPValidationError]:
    """A version as files to recreate it locally: pixi.toml and pixi.lock, or a uv requirements lock

    Args:
        name (str):
        number (int):
        format_ (None | str | Unset): pixi or requirements; the version's own by default

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnvironmentExport | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        name=name,
        number=number,
        format_=format_,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
    format_: None | str | Unset = UNSET,
) -> Any | EnvironmentExport | HTTPValidationError | None:
    """A version as files to recreate it locally: pixi.toml and pixi.lock, or a uv requirements lock

    Args:
        name (str):
        number (int):
        format_ (None | str | Unset): pixi or requirements; the version's own by default

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnvironmentExport | HTTPValidationError
    """

    return sync_detailed(
        name=name,
        number=number,
        client=client,
        format_=format_,
    ).parsed


async def asyncio_detailed(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
    format_: None | str | Unset = UNSET,
) -> Response[Any | EnvironmentExport | HTTPValidationError]:
    """A version as files to recreate it locally: pixi.toml and pixi.lock, or a uv requirements lock

    Args:
        name (str):
        number (int):
        format_ (None | str | Unset): pixi or requirements; the version's own by default

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnvironmentExport | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        name=name,
        number=number,
        format_=format_,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
    format_: None | str | Unset = UNSET,
) -> Any | EnvironmentExport | HTTPValidationError | None:
    """A version as files to recreate it locally: pixi.toml and pixi.lock, or a uv requirements lock

    Args:
        name (str):
        number (int):
        format_ (None | str | Unset): pixi or requirements; the version's own by default

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnvironmentExport | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            name=name,
            number=number,
            client=client,
            format_=format_,
        )
    ).parsed
