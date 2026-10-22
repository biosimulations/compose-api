from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.simulation_cancellation import SimulationCancellation
from ...types import Response


def _get_kwargs(
    simulation_id: int,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/simulations/{simulation_id}".format(
            simulation_id=quote(str(simulation_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | SimulationCancellation | None:
    if response.status_code == 202:
        response_202 = SimulationCancellation.from_dict(response.json())

        return response_202

    if response.status_code == 401:
        response_401 = cast(Any, None)
        return response_401

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
) -> Response[Any | HTTPValidationError | SimulationCancellation]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    simulation_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError | SimulationCancellation]:
    """Cancel a run: withdraw it from the queue, or ask SLURM to cancel its job

     Any signed-in caller who may read the simulation may cancel it, while no simulation has an owner
    (every one is
    public until submissions stamp one, docs/plan-observability.md step 5); then its owner and
    configured admins.

    Args:
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | SimulationCancellation]
    """

    kwargs = _get_kwargs(
        simulation_id=simulation_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    simulation_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | SimulationCancellation | None:
    """Cancel a run: withdraw it from the queue, or ask SLURM to cancel its job

     Any signed-in caller who may read the simulation may cancel it, while no simulation has an owner
    (every one is
    public until submissions stamp one, docs/plan-observability.md step 5); then its owner and
    configured admins.

    Args:
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | SimulationCancellation
    """

    return sync_detailed(
        simulation_id=simulation_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    simulation_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError | SimulationCancellation]:
    """Cancel a run: withdraw it from the queue, or ask SLURM to cancel its job

     Any signed-in caller who may read the simulation may cancel it, while no simulation has an owner
    (every one is
    public until submissions stamp one, docs/plan-observability.md step 5); then its owner and
    configured admins.

    Args:
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | SimulationCancellation]
    """

    kwargs = _get_kwargs(
        simulation_id=simulation_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    simulation_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | SimulationCancellation | None:
    """Cancel a run: withdraw it from the queue, or ask SLURM to cancel its job

     Any signed-in caller who may read the simulation may cancel it, while no simulation has an owner
    (every one is
    public until submissions stamp one, docs/plan-observability.md step 5); then its owner and
    configured admins.

    Args:
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | SimulationCancellation
    """

    return (
        await asyncio_detailed(
            simulation_id=simulation_id,
            client=client,
        )
    ).parsed
