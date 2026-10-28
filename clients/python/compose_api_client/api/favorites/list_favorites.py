from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_detail import ErrorDetail
from ...models.favorite import Favorite
from ...models.favorite_kind import FavoriteKind
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    kind: FavoriteKind | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_kind: None | str | Unset
    if isinstance(kind, Unset):
        json_kind = UNSET
    elif isinstance(kind, FavoriteKind):
        json_kind = kind.value
    else:
        json_kind = kind
    params["kind"] = json_kind

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/favorites",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorDetail | HTTPValidationError | list[Favorite] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = Favorite.from_dict(response_200_item_data)

            response_200.append(response_200_item)

        return response_200

    if response.status_code == 401:
        response_401 = ErrorDetail.from_dict(response.json())

        return response_401

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ErrorDetail | HTTPValidationError | list[Favorite]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    kind: FavoriteKind | None | Unset = UNSET,
) -> Response[ErrorDetail | HTTPValidationError | list[Favorite]]:
    """The caller's stars, newest first; a star on something the caller can no longer read is not listed

    Args:
        kind (FavoriteKind | None | Unset): Only stars of this kind

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | list[Favorite]]
    """

    kwargs = _get_kwargs(
        kind=kind,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    kind: FavoriteKind | None | Unset = UNSET,
) -> ErrorDetail | HTTPValidationError | list[Favorite] | None:
    """The caller's stars, newest first; a star on something the caller can no longer read is not listed

    Args:
        kind (FavoriteKind | None | Unset): Only stars of this kind

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | list[Favorite]
    """

    return sync_detailed(
        client=client,
        kind=kind,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    kind: FavoriteKind | None | Unset = UNSET,
) -> Response[ErrorDetail | HTTPValidationError | list[Favorite]]:
    """The caller's stars, newest first; a star on something the caller can no longer read is not listed

    Args:
        kind (FavoriteKind | None | Unset): Only stars of this kind

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | list[Favorite]]
    """

    kwargs = _get_kwargs(
        kind=kind,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    kind: FavoriteKind | None | Unset = UNSET,
) -> ErrorDetail | HTTPValidationError | list[Favorite] | None:
    """The caller's stars, newest first; a star on something the caller can no longer read is not listed

    Args:
        kind (FavoriteKind | None | Unset): Only stars of this kind

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | list[Favorite]
    """

    return (
        await asyncio_detailed(
            client=client,
            kind=kind,
        )
    ).parsed
