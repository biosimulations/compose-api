from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.hpc_run import HpcRun
from ...models.http_validation_error import HTTPValidationError
from typing import cast


def _get_kwargs(
    *,
    simulator_id: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    params["simulator_id"] = simulator_id

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/results/simulator/build/status",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | HpcRun | None:
    if response.status_code == 200:
        response_200 = HpcRun.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | HpcRun]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    simulator_id: int,
) -> Response[HTTPValidationError | HpcRun]:
    """Get the simulator build status record by its ID

    Args:
        simulator_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | HpcRun]
    """

    kwargs = _get_kwargs(
        simulator_id=simulator_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    simulator_id: int,
) -> HTTPValidationError | HpcRun | None:
    """Get the simulator build status record by its ID

    Args:
        simulator_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | HpcRun
    """

    return sync_detailed(
        client=client,
        simulator_id=simulator_id,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    simulator_id: int,
) -> Response[HTTPValidationError | HpcRun]:
    """Get the simulator build status record by its ID

    Args:
        simulator_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | HpcRun]
    """

    kwargs = _get_kwargs(
        simulator_id=simulator_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    simulator_id: int,
) -> HTTPValidationError | HpcRun | None:
    """Get the simulator build status record by its ID

    Args:
        simulator_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | HpcRun
    """

    return (
        await asyncio_detailed(
            client=client,
            simulator_id=simulator_id,
        )
    ).parsed
