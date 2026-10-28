from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_detail import ErrorDetail
from ...models.http_validation_error import HTTPValidationError
from ...models.image_status import ImageStatus
from ...types import Response


def _get_kwargs(
    simulator_id: int,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/registry/simulators/{simulator_id}/images".format(
            simulator_id=quote(str(simulator_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorDetail | HTTPValidationError | ImageStatus | None:
    if response.status_code == 200:
        response_200 = ImageStatus.from_dict(response.json())

        return response_200

    if response.status_code == 404:
        response_404 = ErrorDetail.from_dict(response.json())

        return response_404

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ErrorDetail | HTTPValidationError | ImageStatus]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    simulator_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> Response[ErrorDetail | HTTPValidationError | ImageStatus]:
    """Whether a simulator's image is built, with its image records and newest build run

    Args:
        simulator_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | ImageStatus]
    """

    kwargs = _get_kwargs(
        simulator_id=simulator_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    simulator_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> ErrorDetail | HTTPValidationError | ImageStatus | None:
    """Whether a simulator's image is built, with its image records and newest build run

    Args:
        simulator_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | ImageStatus
    """

    return sync_detailed(
        simulator_id=simulator_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    simulator_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> Response[ErrorDetail | HTTPValidationError | ImageStatus]:
    """Whether a simulator's image is built, with its image records and newest build run

    Args:
        simulator_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | ImageStatus]
    """

    kwargs = _get_kwargs(
        simulator_id=simulator_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    simulator_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> ErrorDetail | HTTPValidationError | ImageStatus | None:
    """Whether a simulator's image is built, with its image records and newest build run

    Args:
        simulator_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | ImageStatus
    """

    return (
        await asyncio_detailed(
            simulator_id=simulator_id,
            client=client,
        )
    ).parsed
