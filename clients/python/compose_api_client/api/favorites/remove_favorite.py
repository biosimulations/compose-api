from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_detail import ErrorDetail
from ...models.favorite_kind import FavoriteKind
from ...models.favorite_removal import FavoriteRemoval
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    kind: FavoriteKind,
    ref: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/favorites/{kind}/{ref}".format(
            kind=quote(str(kind), safe=""),
            ref=quote(str(ref), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorDetail | FavoriteRemoval | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = FavoriteRemoval.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ErrorDetail.from_dict(response.json())

        return response_400

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
) -> Response[ErrorDetail | FavoriteRemoval | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    kind: FavoriteKind,
    ref: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[ErrorDetail | FavoriteRemoval | HTTPValidationError]:
    """Unstar it; unstarring what is not starred changes nothing

    Args:
        kind (FavoriteKind):
        ref (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | FavoriteRemoval | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        kind=kind,
        ref=ref,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    kind: FavoriteKind,
    ref: str,
    *,
    client: AuthenticatedClient | Client,
) -> ErrorDetail | FavoriteRemoval | HTTPValidationError | None:
    """Unstar it; unstarring what is not starred changes nothing

    Args:
        kind (FavoriteKind):
        ref (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | FavoriteRemoval | HTTPValidationError
    """

    return sync_detailed(
        kind=kind,
        ref=ref,
        client=client,
    ).parsed


async def asyncio_detailed(
    kind: FavoriteKind,
    ref: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[ErrorDetail | FavoriteRemoval | HTTPValidationError]:
    """Unstar it; unstarring what is not starred changes nothing

    Args:
        kind (FavoriteKind):
        ref (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | FavoriteRemoval | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        kind=kind,
        ref=ref,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    kind: FavoriteKind,
    ref: str,
    *,
    client: AuthenticatedClient | Client,
) -> ErrorDetail | FavoriteRemoval | HTTPValidationError | None:
    """Unstar it; unstarring what is not starred changes nothing

    Args:
        kind (FavoriteKind):
        ref (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | FavoriteRemoval | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            kind=kind,
            ref=ref,
            client=client,
        )
    ).parsed
