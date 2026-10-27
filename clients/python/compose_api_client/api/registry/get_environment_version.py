from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.environment_version_detail import EnvironmentVersionDetail
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    name: str,
    number: int,
    *,
    against: int | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_against: int | None | Unset
    if isinstance(against, Unset):
        json_against = UNSET
    else:
        json_against = against
    params["against"] = json_against

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/registry/environments/{name}/versions/{number}".format(
            name=quote(str(name), safe=""),
            number=quote(str(number), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | EnvironmentVersionDetail | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = EnvironmentVersionDetail.from_dict(response.json())

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
) -> Response[Any | EnvironmentVersionDetail | HTTPValidationError]:
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
    against: int | None | Unset = UNSET,
) -> Response[Any | EnvironmentVersionDetail | HTTPValidationError]:
    """One version of an environment: what it was made from, its lock, and what it installed and provides

    Args:
        name (str):
        number (int):
        against (int | None | Unset): Another version of the environment: `changes` lists how this
            one's packages differ from it

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnvironmentVersionDetail | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        name=name,
        number=number,
        against=against,
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
    against: int | None | Unset = UNSET,
) -> Any | EnvironmentVersionDetail | HTTPValidationError | None:
    """One version of an environment: what it was made from, its lock, and what it installed and provides

    Args:
        name (str):
        number (int):
        against (int | None | Unset): Another version of the environment: `changes` lists how this
            one's packages differ from it

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnvironmentVersionDetail | HTTPValidationError
    """

    return sync_detailed(
        name=name,
        number=number,
        client=client,
        against=against,
    ).parsed


async def asyncio_detailed(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
    against: int | None | Unset = UNSET,
) -> Response[Any | EnvironmentVersionDetail | HTTPValidationError]:
    """One version of an environment: what it was made from, its lock, and what it installed and provides

    Args:
        name (str):
        number (int):
        against (int | None | Unset): Another version of the environment: `changes` lists how this
            one's packages differ from it

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnvironmentVersionDetail | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        name=name,
        number=number,
        against=against,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
    against: int | None | Unset = UNSET,
) -> Any | EnvironmentVersionDetail | HTTPValidationError | None:
    """One version of an environment: what it was made from, its lock, and what it installed and provides

    Args:
        name (str):
        number (int):
        against (int | None | Unset): Another version of the environment: `changes` lists how this
            one's packages differ from it

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnvironmentVersionDetail | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            name=name,
            number=number,
            client=client,
            against=against,
        )
    ).parsed
